"""推荐评分引擎 — DeepSeek 相关性评分 + SQLite 去重"""
import json
import logging
from pathlib import Path
from models.deepseek_client import chat
from knowledge.sqlite_store import is_url_already_known

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent

DEFAULT_SCORED = {"results": []}


def score_results(interest_profile: dict, search_results: list[dict]) -> list[dict]:
    """对搜索结果进行相关性评分，返回 score>=60 的结果"""
    if not search_results:
        return []

    # 加载 prompt
    prompt_path = BASE_DIR / "prompts" / "recommendation_prompt.txt"
    with open(prompt_path, "r", encoding="utf-8") as f:
        system_prompt = f.read()

    # 构建用户消息
    user_message = _build_scoring_message(interest_profile, search_results)

    # 调用 DeepSeek
    try:
        response = chat(system_prompt, user_message)
        cleaned = response.strip().strip("```json").strip("```").strip()
        result = json.loads(cleaned)
        scored = _validate_scored_results(result.get("results", []))
        # 只保留推荐的
        recommended = [r for r in scored if r.get("should_recommend")]
        logger.info(f"评分完成: {len(search_results)} 条 → {len(recommended)} 条推荐")
        return recommended
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"推荐评分失败: {e}")
        return []


def deduplicate(results: list[dict]) -> list[dict]:
    """过滤已在知识库或推荐记录中存在的URL + 标题相似度去重"""
    # 1. URL 去重
    filtered = []
    for r in results:
        url = r.get("url", "")
        if not url:
            continue
        if is_url_already_known(url):
            logger.info(f"跳过已知URL: {url[:80]}")
            continue
        filtered.append(r)

    # 2. 标题相似度去重（与已入库的标题比较）
    try:
        from knowledge.sqlite_store import _get_conn
        conn = _get_conn()
        known = conn.execute(
            "SELECT DISTINCT title FROM knowledge_items ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
        known_titles = [r["title"] for r in known if r["title"]]
    except Exception:
        known_titles = []

    if known_titles:
        deduped = []
        for item in filtered:
            if _is_title_duplicate(item.get("title", ""), known_titles):
                logger.info(f"跳过相似标题: {item.get('title', '')[:60]}")
                continue
            deduped.append(item)
        logger.info(f"去重: {len(results)} 条 → {len(deduped)} 条新内容 (URL+标题)")
        return deduped

    logger.info(f"去重: {len(results)} 条 → {len(filtered)} 条新内容 (仅URL)")
    return filtered


def _is_title_duplicate(title: str, known_titles: list[str], threshold: float = 0.75) -> bool:
    """检查标题是否与已知标题高度相似（基于词重叠）"""
    if not title or not known_titles:
        return False

    def _tokenize(text: str) -> set[str]:
        chars = list(text.replace(" ", ""))
        bigrams = {"".join(chars[i:i+2]) for i in range(len(chars)-1)}
        return bigrams | set(chars)

    t1 = _tokenize(title)
    if len(t1) < 3:
        return False

    for kt in known_titles:
        t2 = _tokenize(kt)
        if len(t2) < 3:
            continue
        overlap = len(t1 & t2) / min(len(t1), len(t2))
        if overlap > threshold:
            return True
    return False


def _build_scoring_message(profile: dict, results: list[dict]) -> str:
    """构建评分用户消息"""
    parts = []

    parts.append("【用户兴趣画像】")
    parts.append(f"兴趣摘要: {profile.get('interest_summary', '')}")
    for interest in profile.get("top_interests", [])[:5]:
        tags = ", ".join(interest.get("tags", []))
        parts.append(
            f"  - {interest.get('category', '')} (权重:{interest.get('weight', 0)}) "
            f"标签:{tags} 原因:{interest.get('reason', '')}"
        )
    parts.append(f"偏好分类: {', '.join(profile.get('preferred_categories', []))}")

    parts.append(f"\n【搜索结果（共{len(results)}条）】")
    for i, r in enumerate(results):
        parts.append(
            f"{i+1}. [{r.get('source_query', '')}] {r.get('title', '')}\n"
            f"   URL: {r.get('url', '')}\n"
            f"   摘要: {(r.get('snippet', '') or '')[:200]}"
        )

    return "\n".join(parts)


def _validate_scored_results(results: list[dict]) -> list[dict]:
    """验证并清理评分结果"""
    validated = []
    for r in (results or []):
        score = max(0, min(100, int(r.get("score", 0))))
        validated.append({
            "url": r.get("url", ""),
            "score": score,
            "reason": r.get("reason", ""),
            "category_match": r.get("category_match", ""),
            "should_recommend": score >= 60,
        })
    return validated
