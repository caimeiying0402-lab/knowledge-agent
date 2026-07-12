"""书籍片段推荐 — 基于兴趣画像推荐书籍 + AI 生成核心观点摘要"""
import json
import logging
import time
from pathlib import Path

from models.deepseek_client import chat
from skills.keyword_profile_skill import load_keywords, get_summary

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent


def recommend_books(count: int = 3) -> list[dict]:
    """基于用户兴趣画像推荐书籍，返回含核心观点的书单"""
    keywords = load_keywords()
    summary = get_summary()

    if not keywords and not summary:
        logger.warning("无兴趣画像，无法推荐书籍")
        return []

    prompt_path = BASE_DIR / "prompts" / "book_recommend_prompt.txt"
    system_prompt = prompt_path.read_text(encoding="utf-8")

    # 构建用户画像上下文
    kw_lines = [f"- {kw['term']} (权重: {kw.get('weight', 0):.0%}, 类别: {kw.get('category', '')})"
                for kw in keywords[:8]]
    user_msg = f"""用户画像摘要: {summary}

兴趣关键词:
{chr(10).join(kw_lines)}

请推荐 {count} 本书。"""

    try:
        response = chat(system_prompt, user_msg)
        result = json.loads(response.strip().strip("```json").strip("```").strip())
        books = result.get("books", [])
        logger.info(f"书籍推荐: {len(books)} 本")
        return books
    except Exception as e:
        logger.warning(f"书籍推荐生成失败: {e}")
        return []


def format_book_recommendations(books: list[dict]) -> str:
    """格式化书籍推荐为可读文本"""
    if not books:
        return ""

    lines = []
    for i, b in enumerate(books):
        lines.append(f"#{i+1} 《{b.get('title', '')}》 — {b.get('author', '')}")
        lines.append(f"    豆瓣: {b.get('douban_rating', '')} | {b.get('category', '')}")
        lines.append(f"    推荐理由: {b.get('reason', '')}")
        lines.append(f"    核心观点:")
        for j, insight in enumerate(b.get("key_insights", [])[:3]):
            lines.append(f"      {j+1}. {insight}")
        lines.append("")
    return "\n".join(lines)
