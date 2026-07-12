"""AI 词云画像 — 扫描知识库 → DeepSeek提炼兴趣关键词 → 人审 → JSON"""
import json
import logging
import time
from pathlib import Path

from models.deepseek_client import chat
from knowledge.sqlite_store import get_stats, get_recent_items

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent
PROFILE_PATH = BASE_DIR / "data" / "interest_profile.json"


def generate_profile(force_refresh: bool = False) -> dict:
    """生成用户兴趣关键词画像，返回完整profile dict"""
    # 读取知识库数据
    stats = get_stats()
    recent = get_recent_items(min(stats.get("total", 50), 100))

    if stats.get("total", 0) == 0:
        logger.warning("知识库为空，返回默认画像")
        return _default_profile()

    # 构建知识库摘要
    kb_summary = _build_kb_summary(stats, recent)

    # 加载 prompt
    prompt_path = BASE_DIR / "prompts" / "keyword_profile_prompt.txt"
    system_prompt = prompt_path.read_text(encoding="utf-8")

    # 调用 DeepSeek
    try:
        response = chat(system_prompt, kb_summary)
        result = json.loads(response.strip().strip("```json").strip("```").strip())
    except Exception as e:
        logger.warning(f"画像生成失败: {e}")
        return _default_profile()

    # 组装完整画像
    profile = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "last_curated_at": None,
        "knowledge_base_stats": {
            "total": stats.get("total", 0),
            "categories": stats.get("categories", {}),
        },
        "keywords": result.get("keywords", []),
        "rag_dimensions": result.get("rag_dimensions", []),
        "search_queries": result.get("search_queries", []),
        "excluded_topics": result.get("excluded_topics", []),
        "summary": result.get("summary", ""),
    }

    # 标记所有为自动生成（未人工审阅）
    for kw in profile["keywords"]:
        kw.setdefault("curated", False)
        kw.setdefault("curated_weight", None)

    return profile


def save_profile(profile: dict) -> Path:
    """保存画像到 JSON 文件"""
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"画像已保存: {PROFILE_PATH} ({len(profile.get('keywords', []))} 个关键词)")
    return PROFILE_PATH


def load_profile() -> dict:
    """加载已保存的画像，如果不存在则自动生成"""
    if PROFILE_PATH.exists():
        try:
            return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"画像文件损坏: {e}，重新生成")
    return generate_profile()


def load_rag_dimensions() -> list[dict]:
    """加载 RAG 多维度查询列表（供 Recommendation Agent 使用）"""
    profile = load_profile()
    return profile.get("rag_dimensions", [])


def load_search_queries() -> list[str]:
    """加载搜索查询列表（供 Discovery Agent 使用）"""
    profile = load_profile()
    return profile.get("search_queries", [])


def load_keywords() -> list[dict]:
    """加载关键词列表（含权重）"""
    profile = load_profile()
    return profile.get("keywords", [])


def get_summary() -> str:
    """获取画像摘要"""
    profile = load_profile()
    return profile.get("summary", "")


def regenerate() -> dict:
    """强制重新生成画像"""
    logger.info("强制重新生成兴趣画像...")
    profile = generate_profile(force_refresh=True)
    save_profile(profile)
    return profile


# ── 内部函数 ──

def _build_kb_summary(stats: dict, recent: list[dict]) -> str:
    parts = []
    parts.append(f"知识库总数: {stats.get('total', 0)} 条")
    cats = stats.get("categories", {})
    if cats:
        parts.append("分类分布:")
        for cat, cnt in sorted(cats.items(), key=lambda x: -x[1]):
            parts.append(f"  {cat}: {cnt}条")
    if recent:
        parts.append(f"\n最近 {len(recent)} 条内容:")
        for item in recent:
            title = item.get("title", "")
            cat = item.get("category", "")
            tags = item.get("tags", [])
            summary = (item.get("summary") or "")[:100]
            parts.append(f"  [{cat}] {title}")
            if tags:
                parts.append(f"    标签: {', '.join(tags[:5])}")
            if summary:
                parts.append(f"    摘要: {summary}")
    return "\n".join(parts)


def _default_profile() -> dict:
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "last_curated_at": None,
        "knowledge_base_stats": {"total": 0, "categories": {}},
        "keywords": [],
        "rag_dimensions": [
            {"name": "通用推荐", "query": "有价值的知识内容", "weight": 1.0}
        ],
        "search_queries": ["最新科技资讯"],
        "excluded_topics": [],
        "summary": "知识库为空，使用默认画像",
    }
