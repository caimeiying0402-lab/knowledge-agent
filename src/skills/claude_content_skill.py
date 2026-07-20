"""Claude/DeepSeek 内容生成源 — 每天根据搜索词生成一篇原创文章"""
import json
import logging
import uuid
import time
from pathlib import Path

from models.deepseek_client import chat

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent
PROMPT_PATH = BASE_DIR / "prompts" / "content_generation_prompt.txt"


def generate_daily_article(queries: list[str], recent_titles: list[str] | None = None) -> dict | None:
    """根据搜索词生成一篇原创文章，返回 knowledge item 格式的 dict"""
    if not queries:
        logger.info("无搜索词，跳过内容生成")
        return None

    # 加载 prompt
    if not PROMPT_PATH.exists():
        logger.warning(f"Prompt 文件不存在: {PROMPT_PATH}")
        return None

    with open(PROMPT_PATH, "r", encoding="utf-8") as f:
        system_prompt = f.read()

    # 选话题：取第一个搜索词作为主话题，避免与近期标题重复
    topic = queries[0]
    recent_str = ""
    if recent_titles:
        recent_str = "\n近期已生成过的标题（请避免重复）：\n" + "\n".join(
            f"  - {t}" for t in recent_titles[-10:]
        )

    user_message = f"今日话题: {topic}\n\n参考搜索词（可结合但不限于此）: {', '.join(queries[:5])}{recent_str}"

    # 调用 DeepSeek
    try:
        response = chat(system_prompt, user_message, temperature=0.8, max_tokens=2048)
        cleaned = response.strip().strip("```json").strip("```").strip()
        result = json.loads(cleaned)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"内容生成失败: {e}")
        return None

    title = result.get("title", "").strip()
    content = result.get("content", "").strip()
    category = result.get("category", "科技与AI").strip()
    tags = result.get("tags", [])

    # 质量检查
    if not title or not content:
        logger.warning("生成内容为空")
        return None
    if len(content) < 200:
        logger.warning(f"生成内容过短 ({len(content)} 字)，丢弃")
        return None

    # 构建 knowledge item
    item = {
        "id": str(uuid.uuid4()),
        "title": title,
        "category": category,
        "tags": tags[:5],
        "summary": content[:200] + ("…" if len(content) > 200 else ""),
        "full_content": content,
        "raw_content": content,
        "source_type": "ai_generated",
        "source_path": f"ai://content-generator/{uuid.uuid4().hex[:8]}",
        "source_quality": "high",
        "actionable": None,
        "highlights": [],
        "created_at": int(time.time() * 1000),
        "embedding_status": False,
    }

    logger.info(f"AI 内容生成: [{category}] {title} ({len(content)} 字)")
    return item


def get_recent_generated_titles(days: int = 14) -> list[str]:
    """获取近期 AI 生成的文章标题，用于去重"""
    try:
        from knowledge.sqlite_store import _get_conn

        conn = _get_conn()
        cutoff = int(time.time()) - days * 86400
        rows = conn.execute(
            "SELECT DISTINCT title FROM knowledge_items "
            "WHERE source_type = 'ai_generated' AND created_at >= ?",
            (cutoff * 1000,),
        ).fetchall()
        return [r["title"] for r in rows]
    except Exception:
        return []
