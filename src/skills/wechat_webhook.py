"""
wechat_webhook.py — 企业微信自建应用消息接收服务

功能：
  - 接收企业微信应用推送的消息（文字 / 链接 / 图片）
  - 解密消息体（AES-CBC）
  - 调用现有 ETL 管道（ingest → summarize → feishu）

启动方式：
  cd knowledge-agent
  python src/skills/wechat_webhook.py

环境变量（config/.env）：
  WECOM_TOKEN        企业微信应用 Token（回调配置处填的）
  WECOM_AES_KEY      企业微信应用 EncodingAESKey（43位）
  WECOM_CORP_ID      企业 CorpID
  WECOM_AGENT_ID     应用 AgentID（可选，用于校验）
  INBOX_DIR          图片临时目录，默认 data/inbox/

配合 ngrok 使用：
  ngrok http 5001
  将 https://xxx.ngrok.io/wechat/callback 填入企业微信应用回调 URL
"""

import os
import sys
import hashlib
import base64
import struct
import time
import random
import string
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

# 把 src/ 加入路径，以便直接 import skills.*
sys.path.insert(0, str(BASE_DIR / "src"))
from main import process as etl_process
from skills.multimodal_skill import warmup as warmup_ocr

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(BASE_DIR / "logs" / "wechat_webhook.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

WECOM_TOKEN   = os.getenv("WECOM_TOKEN", "")
WECOM_AES_KEY = os.getenv("WECOM_AES_KEY", "")
WECOM_CORP_ID = os.getenv("WECOM_CORP_ID", "")
INBOX_DIR_RAW = os.getenv("INBOX_DIR", "").strip()
INBOX_DIR     = Path(INBOX_DIR_RAW) if INBOX_DIR_RAW else (BASE_DIR / "data" / "inbox")
INBOX_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)

# ── AES 解密（企业微信标准算法） ────────────────────────────────

def _decrypt_msg(encrypt_b64: str) -> str:
    """解密企业微信 AES-CBC 消息，返回 XML 明文"""
    try:
        from Crypto.Cipher import AES
    except ImportError:
        raise ImportError("请安装 pycryptodome: pip install pycryptodome")

    aes_key = base64.b64decode(WECOM_AES_KEY + "=")
    ciphertext = base64.b64decode(encrypt_b64)
    cipher = AES.new(aes_key, AES.MODE_CBC, aes_key[:16])
    plain = cipher.decrypt(ciphertext)
    # 去掉填充
    pad_size = plain[-1]
    if isinstance(pad_size, int):
        plain = plain[:-pad_size]
    else:
        plain = plain[:-ord(pad_size)]
    # 格式: random(16) + msg_len(4) + xml_content + from_corpid
    msg_len = struct.unpack(">I", plain[16:20])[0]
    xml_content = plain[20 : 20 + msg_len].decode("utf-8")
    return xml_content


def _verify_signature(token: str, timestamp: str, nonce: str, encrypt: str = "") -> str:
    """生成/校验企业微信签名"""
    parts = sorted([token, timestamp, nonce, encrypt])
    return hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()


# ── 消息解析 ────────────────────────────────────────────────────

def _parse_xml(xml_str: str) -> dict:
    """把 XML 消息体解析为 dict"""
    root = ET.fromstring(xml_str)
    return {child.tag: (child.text or "").strip() for child in root}


def _download_image(media_id: str, access_token: str) -> Path:
    """从企业微信下载图片到 inbox 目录，返回本地路径"""
    url = (
        f"https://qyapi.weixin.qq.com/cgi-bin/media/get"
        f"?access_token={access_token}&media_id={media_id}"
    )
    resp = requests.get(url, timeout=30, proxies={"http": None, "https": None})
    # 检查是否返回了错误 JSON（IP 白名单等问题）
    if resp.status_code != 200:
        resp_json = resp.json() if resp.headers.get("Content-Type", "").startswith("application/json") else {}
        logger.error(f"下载图片失败 HTTP {resp.status_code}: {resp.text[:200]}")
        raise RuntimeError(f"下载图片失败: {resp_json.get('errmsg', resp.text[:100])}")
    suffix = ".jpg"
    content_type = resp.headers.get("Content-Type", "")
    if "png" in content_type:
        suffix = ".png"
    filename = INBOX_DIR / f"wechat_{media_id}{suffix}"
    with open(filename, "wb") as f:
        f.write(resp.content)
    logger.info(f"图片已下载到 {filename}")
    return filename


def _get_access_token() -> str:
    """获取企业微信 access_token"""
    corp_id     = os.getenv("WECOM_CORP_ID", "")
    corp_secret = os.getenv("WECOM_CORP_SECRET", "")
    url = (
        f"https://qyapi.weixin.qq.com/cgi-bin/gettoken"
        f"?corpid={corp_id}&corpsecret={corp_secret}"
    )
    resp = requests.get(url, timeout=10, proxies={"http": None, "https": None}).json()
    token = resp.get("access_token", "")
    if not token:
        logger.error(f"获取access_token失败: {resp}")
    return token


# ── ETL 异步封装 ─────────────────────────────────────────────────

def _run_etl_async(source: str, label: str = ""):
    """在后台线程里跑 ETL，不阻塞 HTTP 响应"""
    def _task():
        logger.info(f"[ETL 开始] {label} → {source[:80]}")
        try:
            record = etl_process(source)
            logger.info(f"[ETL 完成] title={record.get('title', '')}")
        except Exception as e:
            logger.error(f"[ETL 失败] {label}: {e}", exc_info=True)

    t = threading.Thread(target=_task, daemon=False)
    t.start()


# ── Flask 路由 ───────────────────────────────────────────────────

@app.route("/wechat/callback", methods=["GET"])
def verify():
    """企业微信回调 URL 验证（GET）"""
    msg_signature = request.args.get("msg_signature", "")
    timestamp     = request.args.get("timestamp", "")
    nonce         = request.args.get("nonce", "")
    echostr       = request.args.get("echostr", "")

    # 验证签名
    sign = _verify_signature(WECOM_TOKEN, timestamp, nonce, echostr)
    if sign != msg_signature:
        logger.warning("签名验证失败")
        return "invalid signature", 403

    # 解密 echostr 并返回
    try:
        plain = _decrypt_msg(echostr)
        # plain 格式: random16 + len4 + echostr_raw + corpid
        # 企业微信文档：echostr 本身已 base64，解密后取出 msg 内容
        # 直接返回解密后的 XML 里的 echostr 原值
        # 实际上对于 URL 验证，直接返回明文 echostr 即可
        aes_key = base64.b64decode(WECOM_AES_KEY + "=")
        from Crypto.Cipher import AES
        ciphertext = base64.b64decode(echostr)
        cipher = AES.new(aes_key, AES.MODE_CBC, aes_key[:16])
        plain_bytes = cipher.decrypt(ciphertext)
        pad_size = plain_bytes[-1] if isinstance(plain_bytes[-1], int) else ord(plain_bytes[-1])
        plain_bytes = plain_bytes[:-pad_size]
        msg_len = struct.unpack(">I", plain_bytes[16:20])[0]
        echo_content = plain_bytes[20 : 20 + msg_len].decode("utf-8")
        logger.info("URL 验证通过")
        return echo_content
    except Exception as e:
        logger.error(f"echostr 解密失败: {e}")
        return "error", 500


@app.route("/wechat/callback", methods=["POST"])
def receive_msg():
    """接收企业微信推送消息（POST）"""
    msg_signature = request.args.get("msg_signature", "")
    timestamp     = request.args.get("timestamp", "")
    nonce         = request.args.get("nonce", "")

    try:
        body      = request.data.decode("utf-8")
        root      = ET.fromstring(body)
        encrypt   = root.findtext("Encrypt", "")
        to_user   = root.findtext("ToUserName", "")
    except Exception as e:
        logger.error(f"XML 解析失败: {e}")
        return "error", 400

    # 校验签名
    sign = _verify_signature(WECOM_TOKEN, timestamp, nonce, encrypt)
    if sign != msg_signature:
        logger.warning("消息签名校验失败")
        return "invalid signature", 403

    # 解密
    try:
        xml_plain = _decrypt_msg(encrypt)
    except Exception as e:
        logger.error(f"消息解密失败: {e}")
        return "error", 500

    msg = _parse_xml(xml_plain)
    msg_type  = msg.get("MsgType", "")
    from_user = msg.get("FromUserName", "unknown")
    logger.info(f"收到消息 type={msg_type} from={from_user}")

    # ── 按消息类型分发 ────────────────────────────────────────────
    if msg_type == "text":
        content = msg.get("Content", "")
        if content:
            _run_etl_async(content, label=f"text from {from_user}")

    elif msg_type == "link":
        url     = msg.get("Url", "")
        title   = msg.get("Title", "")
        desc    = msg.get("Description", "")
        # 优先用 URL；如果 URL 为空，组合 title+desc 作为文本
        source  = url if url else f"{title}\n{desc}"
        if source.strip():
            _run_etl_async(source, label=f"link from {from_user}")

    elif msg_type == "image":
        media_id = msg.get("MediaId", "")
        if media_id:
            try:
                access_token = _get_access_token()
                img_path = _download_image(media_id, access_token)
                _run_etl_async(str(img_path), label=f"image from {from_user}")
            except Exception as e:
                logger.error(f"图片处理失败: {e}", exc_info=True)

    elif msg_type == "voice":
        # 语音暂不处理，记录日志
        logger.info(f"收到语音消息（暂不处理）from={from_user}")

    else:
        logger.info(f"收到未处理的消息类型: {msg_type}")

    # 企业微信要求回复 "success"
    return "success", 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "ts": int(time.time())}), 200


# ── 入口 ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    missing = []
    for key in ["WECOM_TOKEN", "WECOM_AES_KEY", "WECOM_CORP_ID", "WECOM_CORP_SECRET"]:
        if not os.getenv(key):
            missing.append(key)
    if missing:
        logger.warning(f"以下环境变量未配置，部分功能不可用: {missing}")

    # 预热 PaddleOCR（避免首次请求时在线程里初始化导致 GIL 死锁）
    try:
        warmup_ocr()
    except Exception as e:
        logger.warning(f"PaddleOCR 预热失败（图片识别将不可用）: {e}")

    logger.info("企业微信 Webhook 服务启动，监听 :5001/wechat/callback")
    app.run(host="0.0.0.0", port=5001, debug=False)
