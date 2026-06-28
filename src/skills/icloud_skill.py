"""
iCloud Drive 监听 Agent
监听 ~/Library/Mobile Documents/com~apple~CloudDocs/KnowledgeAgentInbox/
将 iPhone 分享的内容接入现有 ETL 管道（ingestion → summary → feishu）。

用法：python src/icloud_skill.py
"""

import json
import logging
import shutil
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# ── 路径 & 环境变量 ──────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / "config" / ".env")

INBOX_DIR   = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/KnowledgeAgentInbox"
QUEUE_DIR   = BASE_DIR / "data" / "inbox"      # 图片/文件暂存
PROCESSED   = BASE_DIR / "data" / "processed"
FAILED      = BASE_DIR / "data" / "failed"

for d in (INBOX_DIR, QUEUE_DIR, PROCESSED, FAILED):
    d.mkdir(parents=True, exist_ok=True)

# ── 导入现有管道 ─────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from skills.ingestion_skill import ingest
from skills.summary_skill   import summarize
from skills.feishu_skill    import write_to_bitable

# ── 日志 ─────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(BASE_DIR / "logs" / "icloud_skill.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ── 核心处理逻辑 ─────────────────────────────────────────────────────────────

def _archive(src: Path, dest_dir: Path) -> None:
    dest = dest_dir / src.name
    # 文件名碰撞时加后缀
    if dest.exists():
        dest = dest_dir / f"{src.stem}_{uuid.uuid4().hex[:6]}{src.suffix}"
    shutil.move(str(src), str(dest))


def _run_pipeline(source: str, source_file: Path) -> None:
    """走完 ingest → summarize → feishu 全链路，写入飞书。"""
    ingested = ingest(source)
    summary  = summarize(ingested["raw_content"])

    record = {
        "id":              str(uuid.uuid4()),
        "source_type":     ingested["type"],
        "source_path":     ingested["source_path"],
        "title":           summary.get("title", ""),
        "summary":         summary.get("summary", ""),
        "full_content":    ingested["raw_content"][:5000],
        "tags":            summary.get("tags", []),
        "category":        summary.get("category", ""),
        "created_at":      int(datetime.now().timestamp() * 1000),
        "embedding_status": False,
    }

    result = write_to_bitable(record)
    log.info("飞书写入结果: %s | 文件: %s", result, source_file.name)


def process_file(path: Path) -> None:
    """根据文件类型分发处理逻辑。"""
    if not path.exists():
        return

    name = path.name
    log.info("检测到新文件: %s", name)

    try:
        # ── 图片：移入 queue 排队，等待多模态接入 ──────────────────────────
        if name.endswith("_image.jpg") or path.suffix.lower() in (".jpg", ".jpeg", ".png"):
            _archive(path, QUEUE_DIR)
            log.info("[QUEUE] 图片已移入 data/inbox/ 等待多模态处理: %s", name)
            return

        # ── JSON 文本 / URL ───────────────────────────────────────────────
        if path.suffix.lower() == ".json":
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            item_type = data.get("type", "text")
            content   = data.get("content", "")

            if not content:
                raise ValueError("JSON 中 content 字段为空")

            # URL 或文本都交给 ingest()，它会自动识别
            _run_pipeline(content, path)
            _archive(path, PROCESSED)
            log.info("[DONE] %s 处理完成并归档", name)
            return

        # ── 其他文件类型：移入 queue ──────────────────────────────────────
        _archive(path, QUEUE_DIR)
        log.info("[QUEUE] 文件已移入 data/inbox/ 等待后续支持: %s", name)

    except Exception as exc:
        log.error("[FAIL] 处理失败 %s — %s", name, exc, exc_info=True)
        try:
            _archive(path, FAILED)
        except Exception:
            pass


# ── watchdog 事件处理器 ───────────────────────────────────────────────────────

class InboxHandler(FileSystemEventHandler):
    # 等待文件写完再处理（iCloud 同步可能分多次写入）
    _SETTLE_SECONDS = 2.0

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        # 忽略临时文件（iCloud 同步中间态）
        if path.name.startswith(".") or path.suffix == ".icloud":
            return
        time.sleep(self._SETTLE_SECONDS)
        process_file(path)

    def on_moved(self, event):
        """iCloud 同步完成后有时会触发 moved 事件（.icloud → 真实文件）。"""
        if event.is_directory:
            return
        path = Path(event.dest_path)
        if path.name.startswith(".") or path.suffix == ".icloud":
            return
        time.sleep(self._SETTLE_SECONDS)
        process_file(path)


# ── 入口 ─────────────────────────────────────────────────────────────────────

def main():
    log.info("iCloud Inbox 监听启动 → %s", INBOX_DIR)
    log.info("按 Ctrl+C 退出")

    # 处理启动前已存在的文件
    existing = [p for p in INBOX_DIR.iterdir()
                if p.is_file() and not p.name.startswith(".") and p.suffix != ".icloud"]
    if existing:
        log.info("发现 %d 个待处理遗留文件，开始处理...", len(existing))
        for p in existing:
            process_file(p)

    observer = Observer()
    observer.schedule(InboxHandler(), str(INBOX_DIR), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("收到退出信号，停止监听...")
        observer.stop()
    observer.join()
    log.info("iCloud Inbox 监听已停止")


if __name__ == "__main__":
    main()
