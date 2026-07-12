"""Obsidian vault 写入 — 知识条目输出为 .md 文件"""
import logging
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent
VAULT_DIR = BASE_DIR / "vault"


def write_to_vault(record: dict) -> Path | None:
    """将一条知识记录写入 Obsidian vault，返回文件路径"""
    if not record or not record.get("full_content"):
        return None

    title = record.get("title", "未命名")[:80]
    category = record.get("category", "其他")
    content = record.get("full_content", "")
    tags = record.get("tags", [])
    source = record.get("source_type", "")
    source_path = record.get("source_path", "")
    created = record.get("created_at", int(time.time() * 1000))
    rid = record.get("id", "")

    # 文件名: 分类/日期-标题.md
    safe_cat = _safe_name(category)
    safe_title = _safe_name(title)[:50]
    date_str = time.strftime("%Y%m%d", time.localtime(created / 1000)) if created > 1e10 else time.strftime("%Y%m%d")
    filename = f"{date_str}-{safe_title}.md"
    file_dir = VAULT_DIR / safe_cat
    file_dir.mkdir(parents=True, exist_ok=True)
    filepath = file_dir / filename

    # YAML frontmatter + 内容
    tag_list = "\n".join(f"  - {t}" for t in tags)
    frontmatter = f"""---
id: "{rid}"
title: "{title}"
category: "{category}"
tags:
{tag_list}
source: "{source}"
source_path: "{source_path}"
created: "{time.strftime('%Y-%m-%d %H:%M', time.localtime(created / 1000)) if created > 1e10 else str(created)}"
---

# {title}

{content}
"""
    filepath.write_text(frontmatter, encoding="utf-8")
    logger.info(f"Obsidian 写入: {filepath}")
    return filepath


def sync_to_vault(dry_run: bool = False) -> int:
    """将 SQLite 知识库中尚未写入 vault 的条目批量导出"""
    from knowledge.sqlite_store import get_recent_items

    items = get_recent_items(200)
    written = 0
    for item in items:
        rid = item.get("id", "")
        cat = _safe_name(item.get("category", "其他"))
        date_str = ""
        created = item.get("created_at", 0)
        if created > 1e10:
            date_str = time.strftime("%Y%m%d", time.localtime(created / 1000))
        else:
            date_str = time.strftime("%Y%m%d")
        filename = f"{date_str}-{_safe_name(item.get('title', ''))[:50]}.md"
        filepath = VAULT_DIR / cat / filename

        # 已存在则跳过
        if filepath.exists():
            continue

        if not dry_run:
            write_to_vault(item)
        written += 1

    logger.info(f"Vault 同步: {written} 条{' (dry run)' if dry_run else ''}")
    return written


def _safe_name(text: str) -> str:
    """将文本转为安全的文件名"""
    text = text.replace("/", "-").replace(":", "-").replace(" ", "-")
    text = re.sub(r'[<>"|?*\\]', '', text)
    return text[:50]
