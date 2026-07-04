"""用户反馈技能 — 记录和管理用户对推荐内容的互动行为"""
import logging
import time
from knowledge.sqlite_store import (
    insert_interaction,
    get_interactions,
    get_interaction_stats,
)

logger = logging.getLogger(__name__)


def record_interaction(
    item_id: str,
    interaction_type: str,
    batch_id: str | None = None,
    score: float | None = None,
    context: str | None = None,
) -> bool:
    """记录一次用户互动

    interaction_type: 'recommended' | 'read' | 'liked' | 'skipped' | 'shared'
    """
    valid_types = {"recommended", "read", "liked", "skipped", "shared"}
    if interaction_type not in valid_types:
        logger.warning(f"无效的互动类型: {interaction_type}")
        return False

    interaction = {
        "item_id": item_id,
        "interaction_type": interaction_type,
        "recommended_score": score,
        "recommended_batch_id": batch_id,
        "context": context,
        "created_at": int(time.time()),
    }

    ok = insert_interaction(interaction)
    if ok:
        logger.info(f"互动已记录: {item_id[:8]} -> {interaction_type}")
    return ok


def record_batch_recommended(
    items: list[dict], batch_id: str, context: str = "scheduled"
) -> int:
    """批量记录'已推荐'互动"""
    count = 0
    for item in items:
        if record_interaction(
            item_id=item.get("id", ""),
            interaction_type="recommended",
            batch_id=batch_id,
            score=item.get("score"),
            context=context,
        ):
            count += 1
    return count


def get_feedback_stats(days: int = 30) -> dict:
    """获取用户反馈统计（最近N天）"""
    return get_interaction_stats(days)


def get_item_feedback_history(item_id: str) -> list[dict]:
    """获取某个知识条目的完整互动历史"""
    return get_interactions(item_id=item_id, limit=50)


def get_skipped_items(days: int = 30) -> set[str]:
    """获取最近被跳过的条目ID集合"""
    stats = get_interaction_stats(days)
    return stats.get("skipped_items", set())


def get_liked_items(days: int = 30) -> set[str]:
    """获取最近被标记为有用的条目ID集合"""
    stats = get_interaction_stats(days)
    return stats.get("liked_items", set())
