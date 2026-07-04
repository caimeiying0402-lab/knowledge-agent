"""用户兴趣画像提取 — 分析知识库，输出用户兴趣画像JSON"""
import json
import logging
from pathlib import Path
from models.deepseek_client import chat
from knowledge.sqlite_store import get_stats, get_recent_items

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent

DEFAULT_PROFILE = {
    "top_interests": [],
    "preferred_categories": [],
    "knowledge_gaps": [],
    "reading_preferences": {"source_types": [], "avg_length": "medium"},
    "interest_summary": "兴趣画像生成失败",
}


def extract_profile() -> dict:
    """从知识库提取用户兴趣画像"""
    try:
        stats = get_stats()
        recent = get_recent_items(50)
    except Exception as e:
        logger.warning(f"读取知识库失败: {e}")
        return _fallback_profile()

    if stats.get("total", 0) == 0:
        logger.info("知识库为空，返回默认画像")
        return DEFAULT_PROFILE

    # 加载 prompt
    prompt_path = BASE_DIR / "prompts" / "interest_profile_prompt.txt"
    with open(prompt_path, "r", encoding="utf-8") as f:
        system_prompt = f.read()

    # 构建用户消息
    user_message = _build_profile_message(stats, recent)

    # 调用 DeepSeek
    try:
        response = chat(system_prompt, user_message)
        result = json.loads(response.strip().strip("```json").strip("```").strip())
        return _validate_profile(result)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"兴趣画像生成失败: {e}")
        return _fallback_profile()


def _build_profile_message(stats: dict, recent: list[dict]) -> str:
    """构建发送给DeepSeek的用户消息"""
    parts = []

    parts.append("【知识库统计】")
    parts.append(f"总条目数: {stats.get('total', 0)}")
    parts.append(f"已向量化: {stats.get('embedded', 0)}")

    categories = stats.get("categories", {})
    if categories:
        parts.append("\n分类分布:")
        for cat, cnt in sorted(categories.items(), key=lambda x: -x[1]):
            parts.append(f"  - {cat}: {cnt}条")

    sources = stats.get("sources", {})
    if sources:
        parts.append("\n来源类型分布:")
        for src, cnt in sources.items():
            parts.append(f"  - {src}: {cnt}条")

    if recent:
        parts.append(f"\n【最近{len(recent)}条知识条目】")
        for item in recent[:30]:
            title = item.get("title", "无标题")
            cat = item.get("category", "未分类")
            tags = item.get("tags", [])
            summary = (item.get("summary") or "")[:120]
            tags_str = ", ".join(tags) if tags else "无标签"
            parts.append(f"  [{cat}] {title} | 标签: {tags_str}")
            if summary:
                parts.append(f"    摘要: {summary}")

    return "\n".join(parts)


def _validate_profile(result: dict) -> dict:
    """验证并补齐画像字段"""
    validated = {}
    validated["top_interests"] = []
    for item in (result.get("top_interests") or [])[:6]:
        validated["top_interests"].append({
            "category": item.get("category", ""),
            "tags": item.get("tags", []),
            "weight": max(0, min(100, int(item.get("weight", 0)))),
            "reason": item.get("reason", ""),
        })
    validated["preferred_categories"] = (result.get("preferred_categories") or [])[:5]
    validated["knowledge_gaps"] = (result.get("knowledge_gaps") or [])[:5]
    reading = result.get("reading_preferences", {}) or {}
    validated["reading_preferences"] = {
        "source_types": reading.get("source_types", []),
        "avg_length": reading.get("avg_length", "medium"),
    }
    validated["interest_summary"] = result.get("interest_summary", "")
    return validated


def _fallback_profile() -> dict:
    """降级方案：纯统计方式生成画像"""
    try:
        stats = get_stats()
        categories = stats.get("categories", {})
        sorted_cats = sorted(categories.items(), key=lambda x: -x[1])

        all_categories = [
            "科技与AI", "产品与工具", "阅读与影视", "职场与创业", "投资与商业",
            "设计与创意", "生活与旅行", "健康与心理", "教育与学习", "人文与哲学",
            "社会与热点", "美食与消费", "人际关系", "个人成长", "效率方法",
            "数据与报告", "自然科学", "技术编程", "医学健康", "其他",
        ]
        existing_cats = set(categories.keys())
        gaps = [c for c in all_categories if c not in existing_cats][:3]

        top = []
        for cat, cnt in sorted_cats[:4]:
            top.append({
                "category": cat,
                "tags": [],
                "weight": min(100, cnt * 10),
                "reason": f"知识库中有{cnt}条相关记录",
            })

        return {
            "top_interests": top,
            "preferred_categories": [c for c, _ in sorted_cats[:5]],
            "knowledge_gaps": gaps,
            "reading_preferences": {"source_types": [], "avg_length": "medium"},
            "interest_summary": "基于知识库统计自动生成",
        }
    except Exception:
        return DEFAULT_PROFILE
