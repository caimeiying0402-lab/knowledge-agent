"""
iCloud Drive 监听 Agent v2
监听 ~/Library/Mobile Documents/com~apple~CloudDocs/KnowledgeAgentInbox/
将 iPhone 分享的内容接入完整 ETL 管道。

v2 改进：
- 图片：OCR → 摘要 → 飞书 + SQLite + Chroma 全链路入库
- 文本/URL：同上全链路入库
- 处理后自动归档到 data/processed/

用法：PYTHONPATH=src python src/skills/icloud_skill.py
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
BASE_DIR = Path(__file__).parent.parent.parent
load_dotenv(BASE_DIR / "config" / ".env")

INBOX_DIR   = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/KnowledgeAgentInbox"
QUEUE_DIR   = BASE_DIR / "data" / "inbox"      # 暂存（不支持的文件类型）
PROCESSED   = BASE_DIR / "data" / "processed"
FAILED      = BASE_DIR / "data" / "failed"

for d in (INBOX_DIR, QUEUE_DIR, PROCESSED, FAILED):
    d.mkdir(parents=True, exist_ok=True)

# ── 日志 ─────────────────────────────────────────────────────────────────────
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "icloud_skill.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ── 核心处理逻辑 ─────────────────────────────────────────────────────────────

# 支持的图片扩展名
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp", ".heic"}


def _archive(src: Path, dest_dir: Path) -> Path:
    """将文件移入目标目录，碰撞时加后缀"""
    dest = dest_dir / src.name
    if dest.exists():
        dest = dest_dir / f"{src.stem}_{uuid.uuid4().hex[:6]}{src.suffix}"
    shutil.move(str(src), str(dest))
    return dest


def _is_image(path: Path) -> bool:
    """判断是否为图片文件"""
    # iPhone 快捷指令分享的图片可能带 _image.jpg 后缀
    return path.suffix.lower() in IMAGE_EXTS or path.name.endswith("_image.jpg")


def process_file(path: Path) -> None:
    """
    根据文件类型分发处理逻辑。

    图片 → OCR → 摘要 → 飞书 + SQLite + Chroma 全链路入库
    JSON → 解析内容 → 全链路入库
    其他 → 移入 queue 等待后续支持
    """
    if not path.exists():
        return

    name = path.name
    log.info("检测到新文件: %s", name)

    try:
        # ── 图片：OCR → 全链路入库 ──────────────────────────────────────
        if _is_image(path):
            _process_image(path)
            return

        # ── JSON 文本 / URL：全链路入库 ────────────────────────────────
        if path.suffix.lower() == ".json":
            _process_json(path)
            return

        # ── 文本文件：全链路入库 ───────────────────────────────────────
        if path.suffix.lower() in (".txt", ".md"):
            _process_text_file(path)
            return

        # ── 其他文件类型：移入 queue ───────────────────────────────────
        _archive(path, QUEUE_DIR)
        log.info("[QUEUE] 文件已移入 data/inbox/ 等待后续支持: %s", name)

    except Exception as exc:
        log.error("[FAIL] 处理失败 %s — %s", name, exc, exc_info=True)
        try:
            _archive(path, FAILED)
        except Exception:
            pass


def _process_image(path: Path) -> None:
    """图片处理：OCR → 摘要 → 飞书 + SQLite + Chroma"""
    from main import process

    log.info("[IMAGE] 开始处理图片: %s", path.name)

    # main.process() 会自动识别文件路径 → ingest_file → OCR
    record = process(str(path))

    if record.get("record_id") or record.get("id"):
        # 归档到 processed
        _archive(path, PROCESSED)
        log.info("[DONE] 图片处理完成并归档: %s → title=%s",
                 path.name, record.get("title", "")[:30])
    else:
        log.warning("[WARN] 图片入库可能失败: %s", path.name)
        _archive(path, FAILED)


def _process_json(path: Path) -> None:
    """JSON 处理：解析内容 → 全链路入库"""
    from main import process

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    content = data.get("content", "")
    if not content:
        raise ValueError("JSON 中 content 字段为空")

    record = process(content)

    if record.get("record_id") or record.get("id"):
        _archive(path, PROCESSED)
        log.info("[DONE] JSON 处理完成并归档: %s", path.name)
    else:
        _archive(path, FAILED)


def _process_text_file(path: Path) -> None:
    """文本文件处理：读取内容 → 全链路入库"""
    from main import process

    with open(path, "r", encoding="utf-8") as f:
        content = f.read().strip()

    if not content:
        raise ValueError("文本文件内容为空")

    record = process(content)

    if record.get("record_id") or record.get("id"):
        _archive(path, PROCESSED)
        log.info("[DONE] 文本文件处理完成并归档: %s", path.name)
    else:
        _archive(path, FAILED)


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
    print("=" * 60)
    print("  iCloud Inbox 监听 Agent v2")
    print("  图片/文本/URL → OCR/采集 → 摘要 → 飞书+SQLite+Chroma")
    print("=" * 60)

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
