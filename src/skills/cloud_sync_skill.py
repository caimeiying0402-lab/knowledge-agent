"""
cloud_sync_skill.py — 云端同步技能

从 Cloudflare Worker (D1) 拉取企微消息并在本地跑 ETL 处理。
Mac 开机后运行此脚本，处理积压消息。

用法:
  cd knowledge-agent
  PYTHONPATH=src python src/skills/cloud_sync_skill.py

环境变量 (config/.env):
  CF_WORKER_URL     Worker URL, 如 https://knowledge-agent-webhook.xxx.workers.dev
  CF_SYNC_API_KEY   同步 API 认证密钥
  INBOX_DIR         图片下载目录, 默认 data/inbox/
"""

import os
import sys
import logging
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

# ── 路径 & 环境变量 ─────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / "config" / ".env")

sys.path.insert(0, str(BASE_DIR / "src"))

CF_WORKER_URL  = os.getenv("CF_WORKER_URL", "").rstrip("/")
CF_SYNC_API_KEY = os.getenv("CF_SYNC_API_KEY", "")

INBOX_DIR_RAW = os.getenv("INBOX_DIR", "").strip()
INBOX_DIR     = Path(INBOX_DIR_RAW) if INBOX_DIR_RAW else (BASE_DIR / "data" / "inbox")
INBOX_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(BASE_DIR / "logs" / "cloud_sync.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ── API 调用 ────────────────────────────────────────────────────

def _headers() -> dict:
    return {"Authorization": f"Bearer {CF_SYNC_API_KEY}"}


def fetch_pending(limit: int = 50) -> list[dict]:
    """从 Worker 拉取未处理消息"""
    resp = requests.get(
        f"{CF_WORKER_URL}/api/pending",
        params={"limit": limit},
        headers=_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("messages", [])


def mark_processed(ids: list[int]) -> bool:
    """标记消息为已处理"""
    resp = requests.post(
        f"{CF_WORKER_URL}/api/processed",
        json={"ids": ids},
        headers=_headers(),
        timeout=30,
    )
    return resp.status_code == 200


def download_image(r2_key: str) -> Path:
    """从 Worker 下载 R2 中的图片到本地 inbox"""
    local_path = INBOX_DIR / r2_key
    local_path.parent.mkdir(parents=True, exist_ok=True)

    resp = requests.get(
        f"{CF_WORKER_URL}/api/image/{r2_key}",
        headers=_headers(),
        timeout=60,
    )
    resp.raise_for_status()
    local_path.write_bytes(resp.content)
    logger.info(f"图片已下载: {local_path} ({len(resp.content)} bytes)")
    return local_path


# ── ETL 处理 ────────────────────────────────────────────────────

def _run_etl(source: str) -> dict | None:
    """调用主 ETL 管道处理单条消息"""
    try:
        from main import process as etl_process
        return etl_process(source)
    except Exception as e:
        logger.error(f"ETL 处理失败: {e}", exc_info=True)
        return None


# ── 主流程 ──────────────────────────────────────────────────────

def sync_once():
    """执行一次同步：拉取 → 处理 → 标记"""
    if not CF_WORKER_URL or not CF_SYNC_API_KEY:
        logger.error("缺少 CF_WORKER_URL 或 CF_SYNC_API_KEY 环境变量")
        return

    logger.info("开始云端同步...")
    messages = fetch_pending()
    if not messages:
        logger.info("没有待处理消息")
        return

    logger.info(f"拉取到 {len(messages)} 条待处理消息")
    processed_ids = []
    failed_count = 0

    for msg in messages:
        msg_id = msg.get("id", "?")
        msg_type = msg.get("msg_type", "unknown")
        try:
            if msg_type == "text":
                content = msg.get("content", "")
                if content.strip():
                    record = _run_etl(content)
                    if record:
                        logger.info(f"✅ [text] id={msg_id} → {record.get('title', '')[:50]}")
                    else:
                        logger.warning(f"⚠️ [text] id={msg_id} ETL返回空")
                else:
                    logger.warning(f"⚠️ [text] id={msg_id} 内容为空，跳过")

            elif msg_type == "link":
                url = msg.get("url", "")
                title = msg.get("title", "")
                desc = msg.get("description", "")
                source = url if url else f"{title}\n{desc}"
                if source.strip():
                    record = _run_etl(source)
                    if record:
                        logger.info(f"✅ [link] id={msg_id} → {record.get('title', '')[:50]}")
                    else:
                        logger.warning(f"⚠️ [link] id={msg_id} ETL返回空")
                else:
                    logger.warning(f"⚠️ [link] id={msg_id} 无有效内容，跳过")

            elif msg_type == "image":
                image_r2_key = msg.get("image_r2_key")
                media_id = msg.get("media_id")

                if image_r2_key:
                    # 从 R2 下载
                    img_path = download_image(image_r2_key)
                    record = _run_etl(str(img_path))
                    if record:
                        logger.info(f"✅ [image] id={msg_id} → {record.get('title', '')[:50]}")
                    else:
                        logger.warning(f"⚠️ [image] id={msg_id} ETL返回空")
                elif media_id:
                    # 降级：尝试从企微直接下载（3天内有效）
                    logger.info(f"[image] id={msg_id} 无R2 key，尝试企微降级下载...")
                    try:
                        from skills.wechat_webhook import _get_access_token, _download_image
                        token = _get_access_token()
                        img_path = _download_image(media_id, token)
                        record = _run_etl(str(img_path))
                        if record:
                            logger.info(f"✅ [image·降级] id={msg_id} → {record.get('title', '')[:50]}")
                    except Exception as e2:
                        logger.error(f"❌ [image·降级] id={msg_id} 失败: {e2}")

            elif msg_type == "voice":
                logger.info(f"⏭️ [voice] id={msg_id} 语音消息暂不处理")

            else:
                logger.info(f"⏭️ [{msg_type}] id={msg_id} 未知消息类型，跳过")

            processed_ids.append(msg_id)

        except Exception as e:
            logger.error(f"❌ 处理失败: id={msg_id}, type={msg_type}, error={e}")
            failed_count += 1
            # 仍然标记为已处理，避免反复重试同一条失败消息
            processed_ids.append(msg_id)

    # 批量标记已处理
    if processed_ids:
        success = mark_processed(processed_ids)
        if success:
            logger.info(f"同步完成: {len(processed_ids)} 条已处理, {failed_count} 条失败")
        else:
            logger.error("标记已处理失败，下次同步将重复处理")

    return len(processed_ids)


def sync_loop(interval: int = 300):
    """循环同步模式（每 interval 秒拉取一次）"""
    logger.info(f"启动循环同步模式，间隔 {interval} 秒")
    while True:
        try:
            sync_once()
        except Exception as e:
            logger.error(f"同步异常: {e}")
        logger.info(f"下次同步: {interval} 秒后")
        time.sleep(interval)


# ── 入口 ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="云端同步: 从 Cloudflare Worker 拉取企微消息并本地处理")
    parser.add_argument("--loop", action="store_true", help="循环同步模式")
    parser.add_argument("--interval", type=int, default=300, help="循环间隔秒数 (默认 300)")
    parser.add_argument("--limit", type=int, default=50, help="每次拉取上限 (默认 50)")
    args = parser.parse_args()

    # 确保 logs 目录
    (BASE_DIR / "logs").mkdir(parents=True, exist_ok=True)

    if args.loop:
        sync_loop(interval=args.interval)
    else:
        sync_once()
