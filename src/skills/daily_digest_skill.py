"""每日汇总推送 — 合并知识库回顾 + 网络发现，一条消息

回顾部分：直接从配置的飞书文档取原文，保留原始换行结构，不做AI加工
发现部分：基于用户画像的网络搜索推荐
"""
import logging
import re
import yaml
from pathlib import Path
from skills.delivery_skill import notify_wechat_kf, notify_email

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent

# 每个文档最多展示的字数（长文档截取头部以适配邮件长度）
MAX_CHARS_PER_DOC = 5000


def _strip_non_text(raw_text: str) -> str:
    """去除邮件无法展示的内容：图片引用、base64、HTML标签等"""
    if not raw_text:
        return ""
    text = raw_text
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    text = re.sub(r'https?://\S+\.(?:png|jpg|jpeg|gif|webp|svg|bmp|heic)(?:\?\S*)?', '',
                  text, flags=re.IGNORECASE)
    text = re.sub(r'data:image/\S+;base64,[A-Za-z0-9+/=]+', '', text)
    text = re.sub(r'<img[^>]*/?>', '', text)
    text = re.sub(r'^[A-Za-z0-9_\-]+\.(?:heic|png|jpg|jpeg|gif|webp|bmp|svg|tiff|raw|mov|mp4)\s*$',
                  '', text, flags=re.IGNORECASE | re.MULTILINE)
    text = re.sub(r'^[A-Fa-f0-9]{8}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{12}\s*$',
                  '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _format_raw_content(raw_text: str, max_chars: int = MAX_CHARS_PER_DOC) -> str:
    """
    保留原始换行结构，只做图片过滤和长度截取。
    不合并行，不重新分段，不改变原文格式。
    """
    if not raw_text:
        return ""

    text = _strip_non_text(raw_text)
    if not text:
        return ""

    if len(text) <= max_chars:
        return text

    # 在 max_chars 附近找最近的换行处截断
    cut = text.rfind("\n", 0, max_chars)
    if cut < max_chars // 2:
        cut = text.rfind("。", 0, max_chars)
    if cut < max_chars // 2:
        cut = max_chars

    return text[:cut] + f"\n\n…（共{len(text)}字，完整内容请在知识库查看）"


def _load_feishu_sources() -> list[dict]:
    """读取飞书同步配置"""
    config_path = BASE_DIR / "config" / "feishu_sources.yaml"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        return config.get("sources", [])
    except FileNotFoundError:
        return []


def _get_source_records(conn) -> list[dict]:
    """从知识库中查找属于配置的飞书文档的记录"""
    sources = _load_feishu_sources()
    if not sources:
        return []

    from skills.feishu_skill import _extract_token_from_url

    records = []
    seen_tokens = set()

    for src in sources:
        url = src.get("url", "").strip()
        if not url:
            continue
        info = _extract_token_from_url(url)
        token = info.get("token", "")
        url_type = info.get("type", "")
        if not token or token in seen_tokens:
            continue
        seen_tokens.add(token)

        # 按 source_path 模糊匹配，找该文档在知识库中的记录
        pattern = f"%{token}%"
        rows = conn.execute(
            """SELECT id, title, raw_content, full_content, summary, category,
                      source_type, source_path, created_at
               FROM knowledge_items
               WHERE source_path LIKE ? AND raw_content IS NOT NULL AND raw_content != ''
               ORDER BY created_at DESC""",
            (pattern,),
        ).fetchall()

        for row in rows:
            records.append({
                "id": row["id"],
                "title": row["title"] or "",
                "raw_content": row["raw_content"] or row["full_content"] or row["summary"] or "",
                "category": row["category"] or "",
                "source_type": row["source_type"] or "",
                "source_path": row["source_path"] or "",
                "url_type": url_type,
            })

    return records


def send_daily_digest() -> bool:
    from knowledge.sqlite_store import (
        get_recommendations, _get_conn,
    )
    import time

    today_start = int(time.time()) - 86400
    conn = _get_conn()

    # ── 1. 知识库回顾：从配置的飞书文档直接取原文 ──
    source_records = _get_source_records(conn)

    # ── 2. 网络发现：外部推荐 ──
    ext_items = get_recommendations(limit=30, delivered_only=True)
    ext_recent = [r for r in ext_items if r.get("recommended_at", 0) > today_start]

    if not source_records and not ext_recent:
        logger.info("今日无内容，跳过汇总推送")
        return False

    lines = ["📋 AIOS 每日精选\n"]

    # ── 回顾部分 ──
    if source_records:
        lines.append("━━━ 📖 知识库回顾 ━━━")

        # 分组：wiki 文档和 bitable 记录分开展示
        wiki_records = [r for r in source_records if r["url_type"] in ("wiki", "docx", "doc")]
        bitable_records = [r for r in source_records if r["url_type"] == "bitable"]

        for rec in wiki_records:
            title = rec["title"][:80]
            raw = rec["raw_content"]
            cat = rec["category"]

            lines.append(f"\n📄 {title}")
            lines.append(f"   📂 {cat} | 原文{len(raw)}字")
            lines.append("")

            # 展示原文，保留原始换行结构
            formatted = _format_raw_content(raw)
            for line in formatted.split("\n"):
                stripped = line.rstrip()
                # 保持空行
                lines.append(f"   {stripped}")
            lines.append("")

        if bitable_records:
            lines.append("\n📊 知识条目")
            for rec in bitable_records:
                title = rec["title"][:80]
                raw = rec["raw_content"]
                cat = rec["category"]
                lines.append(f"\n   ▸ {title} [{cat}]")
                formatted = _format_raw_content(raw, max_chars=2000)
                for line in formatted.split("\n"):
                    lines.append(f"     {line.rstrip()}")

    # ── 发现部分 ──
    if ext_recent:
        if source_records:
            lines.append("")
        lines.append("━━━ 🆕 网络发现 ━━━")
        for r in ext_recent[:3]:
            score = r.get("score", 0)
            star = "⭐" if score >= 80 else "🔵" if score >= 70 else "📎"
            title = r.get("title", "")[:60]
            url = r.get("url", "")
            reason = r.get("reason", "")[:120]
            lines.append(f"\n{star} [{score}分] {title}")
            if reason:
                lines.append(f"   💡 {reason}")
            if url:
                lines.append(f"   🔗 {url[:200]}")

    body = "\n".join(lines)

    # 优先企微，超过2000字或企微失败走邮件
    if len(body) <= 2000:
        if notify_wechat_kf("📋 AIOS 每日精选", body):
            logger.info("每日汇总推送成功（微信客服）")
            return True

    if notify_email("📋 AIOS 每日精选", body):
        logger.info(f"每日汇总推送成功（邮件，{len(body)}字）")
        return True

    return False
