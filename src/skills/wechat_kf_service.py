"""
wechat_kf_service.py — 企业微信客服消息接收服务（个人微信接入）

功能：
  - 接收企业微信客服推送的事件通知（个人微信用户发消息触发）
  - 调用 sync_msg API 拉取具体消息内容（文字/图片/链接/文件）
  - 下载临时素材（图片、文件等）
  - 复用现有 ETL 管道（ingest → summarize → feishu）

与 wechat_webhook.py 的区别：
  - 自建应用：企微成员发消息 → 推送完整消息体 → 直接解析
  - 微信客服：个人用户发消息 → 推送事件通知(只有token) → 需主动拉取消息

启动方式：
  cd knowledge-agent
  python src/skills/wechat_kf_service.py

环境变量（config/.env）：
  WECOM_KF_OPEN_ID   客服账号 OpenKfId
  WECOM_KF_SECRET    客服专用 Secret（用于获取 access_token）
  WECOM_KF_TOKEN     客服回调 Token
  WECOM_KF_AES_KEY   客服回调 EncodingAESKey

配合 cloudflared 使用：
  将 https://xxx.trycloudflare.com/wechat/kf/callback 填入微信客服回调 URL
"""

import os
import sys
import hashlib
import base64
import struct
import time
import logging
import threading
from pathlib import Path
from xml.etree import ElementTree as ET

import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# ── 路径 & 环境变量 ─────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / "config" / ".env")

sys.path.insert(0, str(BASE_DIR / "src"))
from main import process as etl_process
from skills.multimodal_skill import warmup as warmup_ocr

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(BASE_DIR / "logs" / "wechat_kf.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

WECOM_KF_TOKEN   = os.getenv("WECOM_KF_TOKEN", "")
WECOM_KF_AES_KEY = os.getenv("WECOM_KF_AES_KEY", "")
WECOM_KF_OPEN_ID = os.getenv("WECOM_KF_OPEN_ID", "")
WECOM_KF_SECRET  = os.getenv("WECOM_KF_SECRET", "") or os.getenv("WECOM_CORP_SECRET", "")
WECOM_CORP_ID    = os.getenv("WECOM_CORP_ID", "")

INBOX_DIR_RAW = os.getenv("INBOX_DIR", "").strip()
INBOX_DIR     = Path(INBOX_DIR_RAW) if INBOX_DIR_RAW else (BASE_DIR / "data" / "inbox")
INBOX_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)

# ── 消息游标持久化（避免重启后重复处理） ──────────────────────
_CURSOR_FILE = BASE_DIR / "data" / ".kf_cursor.txt"

def _save_cursor(cursor: str):
    """保存下次拉取的 cursor 位置"""
    _CURSOR_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CURSOR_FILE.write_text(cursor)

def _load_cursor() -> str:
    """加载上次保存的 cursor"""
    if _CURSOR_FILE.exists():
        return _CURSOR_FILE.read_text().strip()
    return ""

# ── AES 解密（与企业微信标准算法一致） ─────────────────────────

def _decrypt_msg(encrypt_b64: str) -> str:
    """解密企业微信 AES-CBC 消息，返回 XML 明文"""
    try:
        from Crypto.Cipher import AES
    except ImportError:
        raise ImportError("请安装 pycryptodome: pip install pycryptodome")

    aes_key = base64.b64decode(WECOM_KF_AES_KEY + "=")
    ciphertext = base64.b64decode(encrypt_b64)
    cipher = AES.new(aes_key, AES.MODE_CBC, aes_key[:16])
    plain = cipher.decrypt(ciphertext)
    pad_size = plain[-1]
    if isinstance(pad_size, int):
        plain = plain[:-pad_size]
    else:
        plain = plain[:-ord(pad_size)]
    msg_len = struct.unpack(">I", plain[16:20])[0]
    xml_content = plain[20 : 20 + msg_len].decode("utf-8")
    return xml_content


def _verify_signature(token: str, timestamp: str, nonce: str, encrypt: str = "") -> str:
    """生成/校验企业微信签名"""
    parts = sorted([token, timestamp, nonce, encrypt])
    return hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()


def _parse_xml(xml_str: str) -> dict:
    """把 XML 消息体解析为 dict"""
    root = ET.fromstring(xml_str)
    return {child.tag: (child.text or "").strip() for child in root}


# ── Access Token 管理 ───────────────────────────────────────────

_token_cache = {"value": "", "expires_at": 0}

def _get_access_token() -> str:
    """获取企业微信 access_token（带缓存）"""
    now = time.time()
    if _token_cache["value"] and now < _token_cache["expires_at"]:
        return _token_cache["value"]

    url = (
        f"https://qyapi.weixin.qq.com/cgi-bin/gettoken"
        f"?corpid={WECOM_CORP_ID}&corpsecret={WECOM_KF_SECRET}"
    )
    resp = requests.get(url, timeout=10, proxies={"http": None, "https": None}).json()
    token = resp.get("access_token", "")
    expires_in = resp.get("expires_in", 7200)

    if not token:
        logger.error(f"获取access_token失败: {resp}")
        return ""

    _token_cache["value"] = token
    _token_cache["expires_at"] = now + expires_in - 300  # 提前5分钟刷新
    logger.info("access_token 已刷新")
    return token


# ── 消息同步（sync_msg API） ────────────────────────────────────

def _sync_messages(event_token: str, open_kfid: str = ""):
    """
    调用微信客服 sync_msg API 拉取消息列表。

    Args:
        event_token: 回调事件中携带的 Token（10分钟内有效）
        open_kfid: 客服账号ID，为空则用配置的默认值

    Returns:
        消息列表，每条消息是一个 dict
    """
    kf_id = open_kfid or WECOM_KF_OPEN_ID
    if not kf_id:
        logger.error("open_kfid 未配置且未传入")
        return []

    access_token = _get_access_token()
    if not access_token:
        logger.error("无法获取 access_token")
        return []

    # 先尝试从上次位置继续拉取（增量模式）
    cursor = _load_cursor()

    url = f"https://qyapi.weixin.qq.com/cgi-bin/kf/sync_msg?access_token={access_token}"
    payload = {
        "cursor": cursor,
        "token": event_token,
        "limit": 1000,
        "open_kfid": kf_id,
    }

    try:
        resp = requests.post(url, json=payload, timeout=15,
                           proxies={"http": None, "https": None})
        data = resp.json()
    except Exception as e:
        logger.error(f"sync_msg 请求失败: {e}")
        return []

    if data.get("errcode") != 0:
        logger.warning(f"sync_msg 返回错误: errcode={data.get('errcode')} errmsg={data.get('errmsg')}")
        # 如果是 token 无效等错误，尝试不带 event_token 的请求（频率限制更严但可用）
        if data.get("errcode") in [40029, 41001]:
            payload.pop("token", None)
            try:
                resp = requests.post(url, json=payload, timeout=15,
                                   proxies={"http": None, "https": None})
                data = resp.json()
            except Exception as e2:
                logger.error(f"retry sync_msg 也失败: {e2}")
                return []

    msg_list = data.get("msg_list", [])
    next_cursor = data.get("next_cursor", "")
    has_more = data.get("has_more", 0)

    # 保存游标
    if next_cursor:
        _save_cursor(next_cursor)

    # 如果还有更多，递归拉取（最多3层防死循环）
    if has_more and msg_list and len(msg_list) < 2000:
        more_msgs = _sync_messages_with_cursor(next_cursor, kf_id, access_token, depth=1)
        msg_list.extend(more_msgs)

    logger.info(f"sync_msg 拉取到 {len(msg_list)} 条消息, has_more={has_more}")
    return msg_list


def _sync_messages_with_cursor(cursor: str, open_kfid: str, access_token: str, depth: int = 0) -> list:
    """基于cursor增量拉取更多消息"""
    if depth > 2 or not cursor:
        return []

    url = f"https://qyapi.weixin.qq.com/cgi-bin/kf/sync_msg?access_token={access_token}"
    payload = {
        "cursor": cursor,
        "limit": 1000,
        "open_kfid": open_kfid,
    }
    try:
        resp = requests.post(url, json=payload, timeout=15,
                           proxies={"http": None, "https": None})
        data = resp.json()
    except Exception:
        return []

    msgs = data.get("msg_list", [])
    next_c = data.get("next_cursor", "")
    has_more = data.get("has_more", 0)
    if next_c:
        _save_cursor(next_c)
    if has_more and msgs and depth < 2:
        msgs.extend(_sync_messages_with_cursor(next_c, open_kfid, access_token, depth + 1))
    return msgs


# ── 临时素材下载 ────────────────────────────────────────────────

def _download_temp_media(media_id: str, access_token: str) -> Path:
    """
    从企业微信下载临时素材（图片/语音/视频/文件）到本地。

    Returns:
        本地文件路径
    """
    url = (
        f"https://qyapi.weixin.qq.com/cgi-bin/kf/media/get"
        f"?access_token={access_token}&media_id={media_id}"
    )
    resp = requests.get(url, timeout=30, proxies={"http": None, "https": None})

    if resp.status_code != 200:
        try:
            err = resp.json()
            logger.error(f"下载素材失败: {err}")
        except Exception:
            logger.error(f"下载素材失败 HTTP {resp.status_code}")
        raise RuntimeError(f"下载素材失败: HTTP {resp.status_code}")

    # 从 Content-Disposition 解析文件名或根据类型推断后缀
    suffix = ".bin"
    content_type = resp.headers.get("Content-Type", "")
    content_disp = resp.headers.get("Content-Disposition", "")

    if "image/jpeg" in content_type or "jpg" in content_disp.lower():
        suffix = ".jpg"
    elif "image/png" in content_type or "png" in content_disp.lower():
        suffix = ".png"
    elif "image/gif" in content_type or "gif" in content_disp.lower():
        suffix = ".gif"
    elif "audio" in content_type:
        suffix = ".amr"
    elif "video" in content_type:
        suffix = ".mp4"

    filename = INBOX_DIR / f"kf_{media_id}{suffix}"
    with open(filename, "wb") as f:
        f.write(resp.content)

    logger.info(f"素材已下载: {filename} ({len(resp.content)} bytes)")
    return filename


# ── 消息处理 ────────────────────────────────────────────────────

def _process_single_message(msg: dict):
    """处理单条客服消息，分发到 ETL 管道"""
    msgtype = msg.get("msgtype", "")
    origin = msg.get("origin", 0)  # 3=客户发送, 5=接待人员发送
    external_userid = msg.get("external_userid", "unknown")
    send_time = msg.get("send_time", 0)
    send_time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(send_time)) if send_time else "unknown"

    # 只处理客户发送的消息（origin=3），忽略系统事件和接待人员消息
    if origin != 3:
        logger.debug(f"[跳过] origin={origin} type={msgtype} from={external_userid}")
        return

    label = f"kf-{msgtype} from {external_userid[:10]} @ {send_time_str}"

    try:
        if msgtype == "text":
            content = msg.get("text", {}).get("content", "")
            if content.strip():
                _run_etl_async(content, label=label)

        elif msgtype == "image":
            media_id = msg.get("image", {}).get("media_id", "")
            if media_id:
                access_token = _get_access_token()
                img_path = _download_temp_media(media_id, access_token)
                _run_etl_async(str(img_path), label=label)

        elif msgtype == "link":
            link_info = msg.get("link", {})
            url = link_info.get("url", "")
            title = link_info.get("title", "")
            desc = link_info.get("desc", "")
            source = url if url else f"{title}\n{desc}"
            if source.strip():
                _run_etl_async(source, label=f"kf-link: {title}")

        elif msgtype == "voice":
            media_id = msg.get("voice", {}).get("media_id", "")
            logger.info(f"收到客服语音消息（暂不处理）media_id={media_id}")

        elif msgtype == "video":
            media_id = msg.get("video", {}).get("media_id", "")
            logger.info(f"收到客服视频消息（暂不处理）media_id={media_id}")

        elif msgtype == "file":
            media_id = msg.get("file", {}).get("media_id", "")
            if media_id:
                access_token = _get_access_token()
                file_path = _download_temp_media(media_id, access_token)
                _run_etl_async(str(file_path), label=label)

        elif msgtype == "location":
            loc = msg.get("location", {})
            lat, lon = loc.get("latitude"), loc.get("longitude")
            name = loc.get("name", "")
            logger.info(f"收到客服位置消息: {name} ({lat}, {lon})")

        elif msgtype == "event":
            logger.info(f"收到客服事件: {msg}")

        else:
            logger.info(f"收到未处理的客服消息类型: {msgtype}")

    except Exception as e:
        logger.error(f"处理客服消息失败 [{label}]: {e}", exc_info=True)


def _run_etl_async(source: str, label: str = ""):
    """在后台线程里跑 ETL，不阻塞 HTTP 响应"""
    def _task():
        logger.info(f"[KF-ETL 开始] {label} → {source[:80]}")
        try:
            record = etl_process(source)
            logger.info(f"[KF-ETL 完成] title={record.get('title', '')}")
        except Exception as e:
            logger.error(f"[KF-ETL 失败] {label}: {e}", exc_info=True)

    t = threading.Thread(target=_task, daemon=False)
    t.start()


# ── Flask 路由 ───────────────────────────────────────────────────

@app.route("/wechat/kf/callback", methods=["GET"])
def verify():
    """微信客服回调 URL 验证（GET）— 与自建应用逻辑相同"""
    msg_signature = request.args.get("msg_signature", "")
    timestamp     = request.args.get("timestamp", "")
    nonce         = request.args.get("nonce", "")
    echostr       = request.args.get("echostr", "")

    sign = _verify_signature(WECOM_KF_TOKEN, timestamp, nonce, echostr)
    if sign != msg_signature:
        logger.warning("[KF] 签名验证失败")
        return "invalid signature", 403

    try:
        aes_key = base64.b64decode(WECOM_KF_AES_KEY + "=")
        from Crypto.Cipher import AES
        ciphertext = base64.b64decode(echostr)
        cipher = AES.new(aes_key, AES.MODE_CBC, aes_key[:16])
        plain_bytes = cipher.decrypt(ciphertext)
        pad_size = plain_bytes[-1] if isinstance(plain_bytes[-1], int) else ord(plain_bytes[-1])
        plain_bytes = plain_bytes[:-pad_size]
        msg_len = struct.unpack(">I", plain_bytes[16:20])[0]
        echo_content = plain_bytes[20 : 20 + msg_len].decode("utf-8")
        logger.info("[KF] URL 验证通过")
        return echo_content
    except Exception as e:
        logger.error(f"[KF] echostr 解密失败: {e}")
        return "error", 500


@app.route("/wechat/kf/callback", methods=["POST"])
def receive_event():
    """
    接收微信客服事件推送（POST）。

    流程：接收事件 → 提取 Token → 调用 sync_msg 拉取具体消息 → 分发处理
    """
    msg_signature = request.args.get("msg_signature", "")
    timestamp     = request.args.get("timestamp", "")
    nonce         = request.args.get("nonce", "")

    try:
        body      = request.data.decode("utf-8")
        root      = ET.fromstring(body)
        encrypt   = root.findtext("Encrypt", "")
        to_user   = root.findtext("ToUserName", "")
    except Exception as e:
        logger.error(f"[KF] XML 解析失败: {e}")
        return "error", 400

    sign = _verify_signature(WECOM_KF_TOKEN, timestamp, nonce, encrypt)
    if sign != msg_signature:
        logger.warning("[KF] 消息签名校验失败")
        return "invalid signature", 403

    # 解密事件
    try:
        xml_plain = _decrypt_msg(encrypt)
    except Exception as e:
        logger.error(f"[KF] 事件解密失败: {e}")
        return "error", 500

    event = _parse_xml(xml_plain)
    event_type = event.get("Event", "")
    open_kfid  = event.get("OpenKfId", "")
    event_token = event.get("Token", "")

    logger.info(f"[KF] 收到事件 type={event_type} kf_id={open_kfid} has_token={'yes' if event_token else 'no'}")

    # 仅处理客服消息事件
    if event_type != "kf_msg_or_event":
        logger.info(f"[KF] 忽略非客服事件: {event_type}")
        return "success", 200

    # 异步拉取并处理消息（不阻塞HTTP响应）
    def _pull_and_process():
        try:
            messages = _sync_messages(event_token, open_kfid)
            for msg in messages:
                _process_single_message(msg)
            if not messages:
                logger.info(f"[KF] sync_msg 未拉取到新消息（可能已被消费或无新消息）")
        except Exception as e:
            logger.error(f"[KF] 消息拉取处理异常: {e}", exc_info=True)

    threading.Thread(target=_pull_and_process, daemon=False).start()

    return "success", 200


@app.route("/health", methods=["GET"])
def health():
    kf_ready = bool(WECOM_KF_OPEN_ID and WECOM_KF_SECRET)
    return jsonify({
        "status": "ok",
        "service": "wecom-kf",
        "kf_configured": kf_ready,
        "ts": int(time.time()),
    }), 200


# ── 入口 ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    missing = []
    for key in ["WECOM_KF_TOKEN", "WECOM_KF_AES_KEY", "WECOM_CORP_ID"]:
        if not os.getenv(key):
            missing.append(key)
    if missing:
        logger.warning(f"以下环境变量未配置: {missing}")

    if not WECOM_KF_OPEN_ID:
        logger.warning("WECOM_KF_OPEN_ID 未配置，请在 .env 中填写客服账号 OpenKfId")
    if not WECOM_KF_SECRET:
        logger.warning("WECOM_KF_SECRET 未配置，将回退使用 WECOM_CORP_SECRET")

    # 预热 PaddleOCR
    try:
        warmup_ocr()
    except Exception as e:
        logger.warning(f"PaddleOCR 预热失败: {e}")

    port = int(os.getenv("KF_PORT", "5002"))
    logger.info(f"微信客服 Webhook 服务启动，监听 :{port}/wechat/kf/callback")
    app.run(host="0.0.0.0", port=port, debug=False)
