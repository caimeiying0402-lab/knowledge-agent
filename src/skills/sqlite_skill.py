"""
SQLite Skill — 本地知识库读写

对 sqlite_store 的薄封装，提供面向业务层的接口。
所有操作 try/except 包裹，失败不影响主流程。
"""
import logging
import json
from knowledge.sqlite_store import init_db, insert_item, get_stats, get_recent_items
from knowledge.sqlite_store import search_by_keyword, search_by_category, search_by_tags

logger = logging.getLogger(__name__)


def save_to_sqlite(record: dict) -> bool:
    """
    保存一条知识记录到 SQLite。

    对 record 做轻量清洗（json.dumps 序列化的字段转字符串），
    然后调用 sqlite_store.insert_item。
    """
    try:
        # 确保 JSON 字段是字符串（sqlite_store 内部会再 json.dumps）
        clean = dict(record)
        for field in ["highlights", "tags"]:
            if field in clean and not isinstance(clean[field], str):
                clean[field] = json.dumps(
                    clean[field], ensure_ascii=False
                )
        init_db()
        return insert_item(clean)
    except Exception as e:
        logger.warning(f"SQLite Skill 写入失败（不影响主流程）: {e}")
        return False


def search_knowledge(query: str, limit: int = 20) -> list[dict]:
    """
    全文搜索知识库。

    Args:
        query: 搜索关键词
        limit: 返回结果数量

    Returns:
        [{"title": ..., "summary": ..., "category": ..., "tags": ..., ...}, ...]
    """
    try:
        init_db()
        return search_by_keyword(query, limit)
    except Exception as e:
        logger.warning(f"SQLite 搜索失败: {e}")
        return []


def search_by_category(category: str, limit: int = 20) -> list[dict]:
    """按分类搜索"""
    try:
        init_db()
        return search_by_category(category, limit)
    except Exception as e:
        logger.warning(f"SQLite 分类搜索失败: {e}")
        return []


def search_by_tags(tags: list[str], limit: int = 20) -> list[dict]:
    """按标签搜索"""
    try:
        init_db()
        return search_by_tags(tags, limit)
    except Exception as e:
        logger.warning(f"SQLite 标签搜索失败: {e}")
        return []


def get_knowledge_stats() -> dict:
    """获取知识库统计信息"""
    try:
        init_db()
        return get_stats()
    except Exception as e:
        logger.warning(f"SQLite 统计查询失败: {e}")
        return {"total": 0, "embedded": 0, "categories": {}, "sources": {}}
