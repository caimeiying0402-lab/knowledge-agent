"""
cloud_sync_skill.py — 云端同步技能 (v2: 重试 + 健康监控)

从 Cloudflare Worker (D1) 拉取企微消息并在本地跑 ETL 处理。
Mac 开机后运行此脚本，处理积压消息。

用法:
  cd knowledge-agent
  PYTHONPATH=src python src/skills/cloud_sync_skill.py

环境变量 (config/.env):
  CF_WORKER_URL     Worker URL, 如 https://wechat.your-domain.top
  CF_SYNC_API_KEY   同步 API 认证密钥
  INBOX_DIR         图片下载目录, 默认 data/inbox/
"""

import os
import sys
import logging
import time
import random
from pathlib import Path
from functools import wraps

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


# ── 重试工具 ──────────────────────────────────────────────────────

def retry(max_retries: int = 3, base_delay: float = 1.0):
    """装饰器：指数退避自动重试 HTTP 请求"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_err = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except requests.exceptions.Timeout as e:
                    last_err = e
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                        logger.warning(f"{func.__name__} 超时，{delay:.1f}s 后重试 ({attempt+1}/{max_retries})")
                        time.sleep(delay)
                except requests.exceptions.ConnectionError as e:
                    last_err = e
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                        logger.warning(f"{func.__name__} 连接失败，{delay:.1f}s 后重试 ({attempt+1}/{max_retries})")
                        time.sleep(delay)
                except requests.exceptions.HTTPError as e:
                    # 5xx 重试，4xx 不重试
                    if e.response is not None and e.response.status_code >= 500:
                        last_err = e
                        if attempt < max_retries - 1:
                            delay = base_delay * (2 ** attempt)
                            logger.warning(f"{func.__name__} HTTP {e.response.status_code}，{delay:.1f}s 后重试 ({attempt+1}/{max_retries})")
                            time.sleep(delay)
                    else:
                        raise
            raise last_err
        return wrapper
    return decorator


# ── API 调用 ────────────────────────────────────────────────────

def _headers() -> dict:
    return {"Authorization": f"Bearer {CF_SYNC_API_KEY}"}


@retry(max_retries=3)
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


@retry(max_retries=3)
def mark_processed(ids: list[int]) -> bool:
    """标记消息为已处理"""
    resp = requests.post(
        f"{CF_WORKER_URL}/api/processed",
        json={"ids": ids},
        headers=_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    return True


@retry(max_retries=2)
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


@retry(max_retries=2)
def get_stats() -> dict | None:
    """获取 Worker 端消息统计"""
    resp = requests.get(
        f"{CF_WORKER_URL}/api/stats",
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def check_health() -> bool:
    """检查 Worker 是否可达"""
    try:
        resp = requests.get(f"{CF_WORKER_URL}/health", timeout=5)
        return resp.status_code == 200
    except Exception as e:
        logger.warning(f"Worker 健康检查失败: {e}")
        return False


# ── ETL 处理 ────────────────────────────────────────────────────

def _run_etl(source: str) -> dict | None:
    """调用主 ETL 管道处理单条消息"""
    try:
        from main import process as etl_process
        return etl_process(source)
    except Exception as e:
        logger.error(f"ETL 处理失败: {e}", exc_info=True)
        return None


def _extract_urls(text: str) -> list[str]:
    """从文本中提取所有 URL"""
    import re
    url_pattern = re.compile(
        r'https?://[^\s一-鿿　-〿＀-￯]+'
    )
    urls = url_pattern.findall(text)
    # Deduplicate while preserving order
    seen = set()
    result = []
    for u in urls:
        u = u.rstrip('.,;:!?')  # Strip trailing punctuation
        if u not in seen:
            seen.add(u)
            result.append(u)
    return result


def _run_etl_url(url: str) -> dict | None:
    """通过 ingestion_skill 摄入 URL 内容（展开短链接 + 抓取页面）"""
    try:
        from skills.ingestion_skill import ingest
        ingest_result = ingest(url)
        raw_content = ingest_result.get("raw_content", "")
        platform = ingest_result.get("platform", "link")
        if raw_content and len(raw_content) > 50:
            logger.info(f"URL 内容获取成功: {platform} {len(raw_content)}字")
            # Build enriched source for ETL
            from main import process as etl_process
            return etl_process(raw_content)
        else:
            # Content too short, fall back to treating URL as text
            logger.warning(f"URL 内容不足({len(raw_content)}字)，降级为文本处理")
            return _run_etl(url)
    except Exception as e:
        logger.warning(f"URL 抓取失败({e})，降级为文本处理")
        return _run_etl(url)


# ── 主流程 ──────────────────────────────────────────────────────

def sync_once():
    """执行一次同步：健康检查 → 拉取 → 处理 → 标记 → 统计"""
    if not CF_WORKER_URL or not CF_SYNC_API_KEY:
        logger.error("缺少 CF_WORKER_URL 或 CF_SYNC_API_KEY 环境变量")
        return

    # ── 健康检查 ──
    if not check_health():
        logger.error("Worker 不可达，跳过本次同步")
        return

    # ── 统计概览 ──
    try:
        stats = get_stats()
        if stats:
            logger.info(
                f"Worker 状态: 待处理={stats.get('pending', '?')} "
                f"总数={stats.get('total', '?')} "
                f"最新消息={stats.get('latest_ts', '?')}"
            )
    except Exception:
        logger.debug("无法获取 Worker 统计")

    logger.info("开始云端同步...")
    try:
        messages = fetch_pending()
    except Exception as e:
        logger.error(f"拉取消息失败(已重试): {e}")
        return

    if not messages:
        logger.info("没有待处理消息")
        return

    logger.info(f"拉取到 {len(messages)} 条待处理消息")
    processed_ids = []
    failed_count = 0
    success_types = {"text": 0, "link": 0, "image": 0, "voice": 0}

    for msg in messages:
        msg_id = msg.get("id", "?")
        msg_type = msg.get("msg_type", "unknown")
        try:
            if msg_type == "text":
                content = msg.get("content", "")
                if not content.strip():
                    logger.warning(f"⚠️ [text] id={msg_id} 内容为空，跳过")
                    continue

                # Check for URLs in text — expand and fetch actual page content
                urls = _extract_urls(content)
                if urls:
                    logger.info(f"🔗 [text] id={msg_id} 检测到 {len(urls)} 个URL: {urls[0][:60]}...")
                    for url in urls:
                        record = _run_etl_url(url)
                        if record:
                            logger.info(f"✅ [link] id={msg_id} → {record.get('title', '')[:50]}")
                            success_types["link"] += 1
                        else:
                            logger.warning(f"⚠️ [link] id={msg_id} URL抓取返回空")
                    processed_ids.append(msg_id)
                else:
                    record = _run_etl(content)
                    if record:
                        logger.info(f"✅ [text] id={msg_id} → {record.get('title', '')[:50]}")
                        success_types["text"] += 1
                    else:
                        logger.warning(f"⚠️ [text] id={msg_id} ETL返回空")

            elif msg_type == "link":
                url = msg.get("url", "")
                title = msg.get("title", "")
                desc = msg.get("description", "")
                if url:
                    record = _run_etl_url(url)
                    if record:
                        logger.info(f"✅ [link] id={msg_id} → {record.get('title', '')[:50]}")
                        success_types["link"] += 1
                    else:
                        logger.warning(f"⚠️ [link] id={msg_id} ETL返回空")
                else:
                    logger.warning(f"⚠️ [link] id={msg_id} 无有效内容，跳过")

            elif msg_type == "image":
                image_r2_key = msg.get("image_r2_key")
                media_id = msg.get("media_id")

                if image_r2_key:
                    try:
                        img_path = download_image(image_r2_key)
                        record = _run_etl(str(img_path))
                        if record:
                            logger.info(f"✅ [image] id={msg_id} → {record.get('title', '')[:50]}")
                            success_types["image"] += 1
                        else:
                            logger.warning(f"⚠️ [image] id={msg_id} ETL返回空")
                    except Exception as e2:
                        logger.error(f"❌ [image] id={msg_id} R2下载失败: {e2}")
                        failed_count += 1
                        continue  # 不标记已处理，下次重试

                elif media_id:
                    logger.info(f"[image] id={msg_id} 无R2 key，尝试企微降级下载...")
                    try:
                        from skills.wechat_webhook import _get_access_token, _download_image
                        token = _get_access_token()
                        img_path = _download_image(media_id, token)
                        record = _run_etl(str(img_path))
                        if record:
                            logger.info(f"✅ [image·降级] id={msg_id} → {record.get('title', '')[:50]}")
                            success_types["image"] += 1
                    except Exception as e2:
                        logger.error(f"❌ [image·降级] id={msg_id} 失败: {e2}")
                        failed_count += 1
                        continue

            elif msg_type == "voice":
                logger.info(f"⏭️ [voice] id={msg_id} 语音消息暂不处理")
                success_types["voice"] += 1

            else:
                logger.info(f"⏭️ [{msg_type}] id={msg_id} 未知消息类型，跳过")

            processed_ids.append(msg_id)

        except Exception as e:
            logger.error(f"❌ 处理失败: id={msg_id}, type={msg_type}, error={e}")
            failed_count += 1
            # 网络/临时错误不标记已处理，下次重试
            if isinstance(e, (requests.RequestException, OSError)):
                continue
            processed_ids.append(msg_id)

    # ── 批量标记已处理 ──
    if processed_ids:
        try:
            mark_processed(processed_ids)
        except Exception as e:
            logger.error(f"标记已处理失败(已重试): {e}，下次同步将重复处理")
            return

    # ── 同步报告 ──
    total_success = sum(success_types.values())
    logger.info(
        f"同步完成: {total_success} 成功 / {failed_count} 失败 / "
        f"分类: text={success_types['text']} link={success_types['link']} "
        f"image={success_types['image']} voice={success_types['voice']}"
    )

    return len(processed_ids)


def sync_loop(interval: int = 60):
    """循环同步模式 — 智能轮询：有消息时 30s，空闲时 60s"""
    logger.info(f"启动实时同步模式（每 {interval}s 轮询 Worker）")
    idle_interval = max(interval, 60)   # idle: 60s
    active_interval = max(interval // 2, 30)  # active: 30s
    fail_streak = 0

    while True:
        try:
            count = sync_once()
            if count is None:
                fail_streak += 1
                backoff = min(300, 30 * fail_streak)
                logger.info(f"同步失败，{backoff}s 后重试...")
                time.sleep(backoff)
            elif count > 0:
                fail_streak = 0
                logger.info(f"处理后继续监听（{active_interval}s 间隔）")
                time.sleep(active_interval)
            else:
                fail_streak = 0
                time.sleep(idle_interval)
        except KeyboardInterrupt:
            logger.info("收到中断信号，退出同步")
            break
        except Exception as e:
            logger.error(f"同步异常: {e}")
            fail_streak += 1
            time.sleep(min(300, 30 * fail_streak))


# ── 入口 ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="云端同步: 从 Cloudflare Worker 拉取企微消息并本地处理")
    parser.add_argument("--loop", action="store_true", help="循环同步模式")
    parser.add_argument("--interval", type=int, default=60, help="轮询间隔秒数 (默认 60)")
    parser.add_argument("--limit", type=int, default=50, help="每次拉取上限 (默认 50)")
    parser.add_argument("--stats", action="store_true", help="仅显示 Worker 端统计信息")
    args = parser.parse_args()

    # 确保 logs 目录
    (BASE_DIR / "logs").mkdir(parents=True, exist_ok=True)

    if args.stats:
        if check_health():
            print("Worker 状态: 在线 ✅")
            try:
                stats = get_stats()
                if stats:
                    print(f"  待处理消息: {stats.get('pending', '?')}")
                    print(f"  总消息数:   {stats.get('total', '?')}")
                    ts = stats.get('latest_ts')
                    if ts:
                        from datetime import datetime
                        print(f"  最新消息:   {datetime.fromtimestamp(ts)}")
            except Exception as e:
                print(f"获取统计失败: {e}")
        else:
            print("Worker 状态: 离线 ❌")
    elif args.loop:
        sync_loop(interval=args.interval)
    else:
        sync_once()
