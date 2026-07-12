"""
wechat_kf_poller.py — 企业微信客服消息主动拉取服务（个人微信接入·方案B）

✅ 优势（相比回调推送方案）：
  - 不需要 Cloudflare 隧道（无固定公网IP也可以）
  - 不需要配置回调 URL（企业微信后台无需填 URL/Token/AESKey）
  - 电脑重启后自动恢复（只需要重启这个脚本）
  - 完全本地运行，零公网依赖

工作原理：
  每 5 秒调用一次企业微信 sync_msg API 拉取新消息
  → 下载图片/文件临时素材
  → 调用 ETL 管道（ingest → summarize → feishu）
  → 保存游标（cursor），重启后不重复处理

启动方式：
  cd knowledge-agent
  python src/skills/wechat_kf_poller.py

后台运行（推荐）：
  nohup python src/skills/wechat_kf_poller.py > logs/wechat_kf.log 2>&1 &

开机自启（macOS）：
  见本文件末尾的 LaunchAgent 配置说明

环境变量（config/.env）：
  WECOM_KF_OPEN_ID   → 客服账号 OpenKfId（必填）
  WECOM_KF_SECRET    → 客服专用 Secret（可选，留空则用 WECOM_CORP_SECRET）
  WECOM_CORP_ID     → 企业 CorpID（必填）
  WECOM_CORP_SECRET  → 企业 Secret（必填，回退用）
  KF_POLLER_INTERVAL → 拉取间隔秒数（默认 5）
"""

import os
import sys
import time
import logging
import threading
from pathlib import Path

import requests
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
    force=True,
)
logger = logging.getLogger(__name__)

WECOM_KF_OPEN_ID  = os.getenv("WECOM_KF_OPEN_ID", "")
# 客服Secret优先，否则用自建应用Secret（应用级别的token才有客服API权限）
_WECOM_KF_SECRET_RAW = os.getenv("WECOM_KF_SECRET", "").strip()
WECOM_CORP_SECRET   = os.getenv("WECOM_CORP_SECRET", "")
if _WECOM_KF_SECRET_RAW:
    WECOM_KF_SECRET = _WECOM_KF_SECRET_RAW
    logger.info(f"使用客服专用 Secret（{_WECOM_KF_SECRET_RAW[:6]}...）")
else:
    WECOM_KF_SECRET = WECOM_CORP_SECRET
    logger.info(f"使用自建应用 Secret（{WECOM_CORP_SECRET[:6]}...）作为客服凭证")
WECOM_CORP_ID     = os.getenv("WECOM_CORP_ID", "")
POLLER_INTERVAL    = int(os.getenv("KF_POLLER_INTERVAL", "30"))  # 默认 30 秒，避免触发 45009

INBOX_DIR_RAW = os.getenv("INBOX_DIR", "").strip()
INBOX_DIR = Path(INBOX_DIR_RAW) if INBOX_DIR_RAW else (BASE_DIR / "data" / "inbox")
INBOX_DIR.mkdir(parents=True, exist_ok=True)

# ── 消息游标持久化 ──────────────────────────────────────────────
_CURSOR_FILE = BASE_DIR / "data" / ".kf_cursor.txt"

def _save_cursor(cursor: str):
    _CURSOR_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CURSOR_FILE.write_text(cursor)

def _load_cursor() -> str:
    if _CURSOR_FILE.exists():
        return _CURSOR_FILE.read_text().strip()
    return ""

# ── Access Token 管理 ───────────────────────────────────────────
_token_cache = {"value": "", "expires_at": 0}

def _get_access_token() -> str:
    now = time.time()
    if _token_cache["value"] and now < _token_cache["expires_at"]:
        return _token_cache["value"]

    url = (
        f"https://qyapi.weixin.qq.com/cgi-bin/gettoken"
        f"?corpid={WECOM_CORP_ID}&corpsecret={WECOM_KF_SECRET}"
    )
    try:
        resp = requests.get(url, timeout=10, proxies={"http": None, "https": None}).json()
    except Exception as e:
        logger.error(f"获取 access_token 网络错误: {e}")
        return _token_cache["value"]  # 返回旧 token 重试

    token = resp.get("access_token", "")
    expires_in = resp.get("expires_in", 7200)

    if not token:
        logger.error(f"获取 access_token 失败: {resp}")
        return _token_cache["value"]

    _token_cache["value"] = token
    _token_cache["expires_at"] = now + expires_in - 300
    logger.info("access_token 已刷新")
    return token


# ── 消息同步（sync_msg API，主动拉取） ───────────────────────
def _sync_messages() -> list:
    """
    调用 sync_msg API 拉取新消息。
    使用持久化 cursor 实现增量拉取，避免重复处理。
    """
    kf_id = WECOM_KF_OPEN_ID
    if not kf_id:
        logger.error("WECOM_KF_OPEN_ID 未配置，跳过本次拉取")
        return []

    access_token = _get_access_token()
    if not access_token:
        return []

    cursor = _load_cursor()

    url = f"https://qyapi.weixin.qq.com/cgi-bin/kf/sync_msg?access_token={access_token}"
    payload = {
        "cursor": cursor,
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
   
    errcode = data.get("errcode", 0)
    if errcode != 0:
        errmsg = data.get('errmsg', '')
        hint = data.get('hint', '')
        logger.warning(f"[sync_msg] errcode={errcode} errmsg={errmsg} hint={hint}")
        # 45009 = 频率限制，需要退避，返回 None 让主循环识别
        if errcode == 45009:
            logger.error("⚠️  触发 API 频率限制（45009），将在下次循环等待 60 秒")
            time.sleep(2)  # 稍微等待后再返回，避免立刻重试
            return None
        # token 过期，清除缓存重试一次
        if errcode in [40001, 42001]:
            _token_cache["value"] = ""
            access_token = _get_access_token()
            if access_token:
                url = f"https://qyapi.weixin.qq.com/cgi-bin/kf/sync_msg?access_token={access_token}"
                try:
                    resp = requests.post(url, json=payload, timeout=15,
                                       proxies={"http": None, "https": None})
                    data = resp.json()
                    errcode = data.get("errcode", 0)
                except Exception:
                    return []
        if data.get("errcode", 0) != 0:
            logger.warning(f"[sync_msg重试] errcode={data.get('errcode')} errmsg={data.get('errmsg')} hint={data.get('hint','')}")
            return []

    msg_list = data.get("msg_list", [])
    next_cursor = data.get("next_cursor", "")
    has_more = data.get("has_more", 0)

    # 保存游标
    if next_cursor:
        _save_cursor(next_cursor)

    # 如果还有更多消息，继续拉取（最多再多拉 2 轮）
    if has_more and next_cursor:
        time.sleep(0.3)
        more_msgs = _sync_messages_more(next_cursor, kf_id, access_token, depth=1)
        msg_list.extend(more_msgs)

    if msg_list:
        logger.info(f"拉取到 {len(msg_list)} 条新消息")
    return msg_list


def _sync_messages_more(cursor: str, open_kfid: str, access_token: str, depth: int = 0) -> list:
    if depth > 2 or not cursor:
        return []

    url = f"https://qyapi.weixin.qq.com/cgi-bin/kf/sync_msg?access_token={access_token}"
    payload = {"cursor": cursor, "limit": 1000, "open_kfid": open_kfid}

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
    if has_more and next_c and depth < 2:
        msgs.extend(_sync_messages_more(next_c, open_kfid, access_token, depth + 1))
    return msgs


# ── 临时素材下载 ────────────────────────────────────────────────
def _download_temp_media(media_id: str, access_token: str) -> Path:
    url = (
        f"https://qyapi.weixin.qq.com/cgi-bin/kf/media/get"
        f"?access_token={access_token}&media_id={media_id}"
    )
    try:
        resp = requests.get(url, timeout=30, proxies={"http": None, "https": None})
    except Exception as e:
        raise RuntimeError(f"下载素材网络错误: {e}")

    if resp.status_code != 200:
        try:
            err = resp.json()
            logger.error(f"下载素材失败: {err}")
        except Exception:
            logger.error(f"下载素材失败 HTTP {resp.status_code}")
        raise RuntimeError(f"下载素材失败: HTTP {resp.status_code}")

    # 推断文件后缀
    suffix = ".bin"
    content_type = resp.headers.get("Content-Type", "").lower()
    if "image/jpeg" in content_type or "jpg" in resp.headers.get("Content-Disposition", "").lower():
        suffix = ".jpg"
    elif "image/png" in content_type:
        suffix = ".png"
    elif "image/gif" in content_type:
        suffix = ".gif"
    elif "audio" in content_type:
        suffix = ".amr"
    elif "video" in content_type:
        suffix = ".mp4"

    filename = INBOX_DIR / f"kf_{media_id}{suffix}"
    with open(filename, "wb") as f:
        f.write(resp.content)

    logger.info(f"素材已下载: {filename.name} ({len(resp.content)} bytes)")
    return filename


# ── 消息处理 ────────────────────────────────────────────────────
def _process_single_message(msg: dict):
    msgtype = msg.get("msgtype", "")
    origin = msg.get("origin", 0)  # 3=客户发送, 5=接待人员发送
    external_userid = msg.get("external_userid", "unknown")
    send_time = msg.get("send_time", 0)
    send_time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(send_time)) if send_time else "unknown"

    # 保存最新的用户 ID（供后续推送通知使用）
    if external_userid and external_userid != "unknown":
        user_file = BASE_DIR / "data" / ".kf_user_id"
        user_file.parent.mkdir(parents=True, exist_ok=True)
        user_file.write_text(external_userid)

    # 只处理客户发送的消息（origin=3）
    if origin != 3:
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

        elif msgtype == "file":
            media_id = msg.get("file", {}).get("media_id", "")
            if media_id:
                access_token = _get_access_token()
                file_path = _download_temp_media(media_id, access_token)
                _run_etl_async(str(file_path), label=label)

        elif msgtype == "voice":
            media_id = msg.get("voice", {}).get("media_id", "")
            logger.info(f"收到语音消息（暂不处理）media_id={media_id}")

        elif msgtype == "event":
            logger.info(f"收到事件消息: {msg.get('event', {})}")

        else:
            logger.info(f"收到未处理的消息类型: {msgtype}")

    except Exception as e:
        logger.error(f"处理消息失败 [{label}]: {e}", exc_info=True)


def _run_etl_async(source: str, label: str = ""):
    """在后台线程跑 ETL，不阻塞拉取循环"""
    def _task():
        logger.info(f"[KF-ETL 开始] {label}")
        try:
            record = etl_process(source)
            title = record.get("title", "")
            logger.info(f"[KF-ETL 完成] title={title}")
        except Exception as e:
            logger.error(f"[KF-ETL 失败] {label}: {e}", exc_info=True)

    t = threading.Thread(target=_task, daemon=False)
    t.start()


# ── 主循环 ──────────────────────────────────────────────────────
_running = True

def _polling_loop():
    """主动拉取消息的主循环"""
    global _running
    logger.info(f"消息拉取循环已启动，间隔 {POLLER_INTERVAL}s，客服账号={WECOM_KF_OPEN_ID}")
    consecutive_errors = 0
    loop_count = 0

    while _running:
        try:
            messages = _sync_messages()
            if messages is None:
                # 遇到 45009 频率限制
                consecutive_errors += 1
                logger.warning(f"频率限制退避中（连续第 {consecutive_errors} 次），等待 60 秒...")
                time.sleep(60)
                continue
            if messages:
                consecutive_errors = 0
                for msg in messages:
                    _process_single_message(msg)
            else:
                consecutive_errors = 0
                logger.debug("本轮无新消息")
        except Exception as e:
            consecutive_errors += 1
            logger.error(f"拉取循环异常（第 {consecutive_errors} 次）: {e}", exc_info=True)
            # 连续错误超过 5 次，等待更长时间
            if consecutive_errors >= 5:
                logger.warning("连续错误过多，等待 60s 后重试...")
                time.sleep(60)
                consecutive_errors = 0
                continue

        # 等待下次拉取
        for _ in range(POLLER_INTERVAL):
            if not _running:
                break
            time.sleep(1)


def _signal_handler(sig, frame):
    global _running
    logger.info("收到停止信号，正在退出...")
    _running = False


if __name__ == "__main__":
    import signal

    # 参数检查
    if not WECOM_KF_OPEN_ID:
        logger.error("❌ WECOM_KF_OPEN_ID 未配置，请在 config/.env 中填写")
        logger.error("   获取方式：企业微信管理后台 → 微信客服 → 点击客服账号名称 → 复制 OpenKfId")
        sys.exit(1)

    if not WECOM_CORP_ID or not WECOM_KF_SECRET:
        logger.error("❌ WECOM_CORP_ID 或 WECOM_KF_SECRET 未配置")
        sys.exit(1)

    # 后台预热 PaddleOCR（不阻塞轮询启动）
    logger.info("后台预热 PaddleOCR 引擎...")
    def _warmup_bg():
        try:
            warmup_ocr()
            logger.info("PaddleOCR 就绪（后台预热完成）")
        except Exception as e:
            logger.warning(f"PaddleOCR 预热失败: {e}")
    threading.Thread(target=_warmup_bg, daemon=True).start()

    # 注册退出信号
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    logger.info("=" * 60)
    logger.info("  企业微信客服消息拉取服务（方案B·主动拉取）")
    logger.info(f"  客服账号: {WECOM_KF_OPEN_ID}")
    logger.info(f"  拉取间隔: {POLLER_INTERVAL}s")
    logger.info(f"  日志文件: {BASE_DIR / 'logs' / 'wechat_kf.log'}")
    logger.info("  按 Ctrl+C 停止服务")
    logger.info("=" * 60)

    # 启动拉取循环（当前线程，不另开线程，方便 Ctrl+C 退出）
    _polling_loop()

    logger.info("服务已停止")
