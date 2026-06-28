"""
SQLite 本地知识库 — 数据持久化与查询

数据库文件: data/knowledge.db
与飞书多维表格字段对齐，同时适配 SQL 查询
"""
import sqlite3
import json
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# 数据库文件路径
_DB_PATH = Path(__file__).parent.parent.parent / "data" / "knowledge.db"
# 线程本地连接（sqlite3 同一个连接不能跨线程使用）
_local = threading.local()

DDL = """
CREATE TABLE IF NOT EXISTS knowledge_items (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_path TEXT,
    title TEXT NOT NULL,
    summary TEXT,
    full_content TEXT,
    highlights TEXT,
    tags TEXT,
    category TEXT,
    source_quality TEXT,
    actionable INTEGER DEFAULT 0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    embedding_status INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_category ON knowledge_items(category);
CREATE INDEX IF NOT EXISTS idx_created_at ON knowledge_items(created_at);
CREATE INDEX IF NOT EXISTS idx_source_type ON knowledge_items(source_type);
CREATE INDEX IF NOT EXISTS idx_embedding_status ON knowledge_items(embedding_status);
"""


def _get_conn(db_path: str = None) -> sqlite3.Connection:
    """获取当前线程的数据库连接（线程安全）"""
    path = db_path or str(_DB_PATH)
    conn = getattr(_local, "conn", None)
    if conn is None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


def init_db(db_path: str = None) -> sqlite3.Connection:
    """初始化数据库（创建表结构），幂等"""
    conn = _get_conn(db_path)
    conn.executescript(DDL)
    conn.commit()
    logger.info(f"SQLite 数据库已就绪: {db_path or _DB_PATH}")
    return conn


def insert_item(record: dict) -> bool:
    """
    插入一条知识记录。
    如果 id 已存在则跳过（幂等）。
    """
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO knowledge_items
               (id, source_type, source_path, title, summary, full_content,
                highlights, tags, category, source_quality, actionable,
                created_at, updated_at, embedding_status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                record.get("id", ""),
                record.get("source_type", ""),
                record.get("source_path", ""),
                record.get("title", ""),
                record.get("summary", ""),
                record.get("full_content", ""),
                json.dumps(record.get("highlights", []), ensure_ascii=False),
                json.dumps(record.get("tags", []), ensure_ascii=False),
                record.get("category", ""),
                record.get("source_quality", ""),
                1 if record.get("actionable") else 0,
                record.get("created_at", 0),
                record.get("created_at", 0),  # updated_at = created_at 初值
                1 if record.get("embedding_status") else 0,
            ),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.warning(f"SQLite 写入失败: {e}")
        return False


def update_item(record_id: str, updates: dict) -> bool:
    """更新一条记录的部分字段"""
    if not updates:
        return True
    conn = _get_conn()
    set_clause = ", ".join(f"{k}=?" for k in updates.keys())
    values = list(updates.values()) + [record_id]
    try:
        conn.execute(
            f"UPDATE knowledge_items SET {set_clause} WHERE id=?",
            values,
        )
        conn.commit()
        return True
    except Exception as e:
        logger.warning(f"SQLite 更新失败: {e}")
        return False


def get_item(record_id: str) -> dict | None:
    """按 ID 获取单条记录"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM knowledge_items WHERE id=?", (record_id,)
    ).fetchone()
    return _row_to_dict(row) if row else None


def search_by_keyword(keyword: str, limit: int = 20) -> list[dict]:
    """全文关键词搜索（LIKE 匹配 title + summary）"""
    conn = _get_conn()
    pattern = f"%{keyword}%"
    rows = conn.execute(
        """SELECT * FROM knowledge_items
           WHERE title LIKE ? OR summary LIKE ?
           ORDER BY created_at DESC LIMIT ?""",
        (pattern, pattern, limit),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def search_by_category(category: str, limit: int = 20) -> list[dict]:
    """按分类搜索"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM knowledge_items WHERE category=? ORDER BY created_at DESC LIMIT ?",
        (category, limit),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def search_by_tags(tags: list[str], limit: int = 20) -> list[dict]:
    """按标签搜索（包含任一标签即匹配）"""
    if not tags:
        return get_recent_items(limit)
    conn = _get_conn()
    # 对每个 tag 构建 LIKE 条件
    conditions = " OR ".join(["tags LIKE ?" for _ in tags])
    patterns = [f"%{t}%" for t in tags]
    rows = conn.execute(
        f"SELECT * FROM knowledge_items WHERE {conditions} ORDER BY created_at DESC LIMIT ?",
        patterns + [limit],
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_recent_items(limit: int = 20) -> list[dict]:
    """获取最近入库的记录"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM knowledge_items ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_unembedded_items(limit: int = 50) -> list[dict]:
    """获取尚未向量化的记录"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM knowledge_items WHERE embedding_status=0 ORDER BY created_at ASC LIMIT ?",
        (limit,),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def mark_embedded(record_id: str) -> bool:
    """标记一条记录已完成向量化"""
    return update_item(record_id, {"embedding_status": 1})


def get_stats() -> dict:
    """获取知识库统计信息"""
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) FROM knowledge_items").fetchone()[0]
    categories = conn.execute(
        "SELECT category, COUNT(*) as cnt FROM knowledge_items GROUP BY category ORDER BY cnt DESC"
    ).fetchall()
    sources = conn.execute(
        "SELECT source_type, COUNT(*) as cnt FROM knowledge_items GROUP BY source_type ORDER BY cnt DESC"
    ).fetchall()
    embedded = conn.execute(
        "SELECT COUNT(*) FROM knowledge_items WHERE embedding_status=1"
    ).fetchone()[0]

    return {
        "total": total,
        "embedded": embedded,
        "categories": {r["category"]: r["cnt"] for r in categories},
        "sources": {r["source_type"]: r["cnt"] for r in sources},
    }


def delete_item(record_id: str) -> bool:
    """删除一条记录"""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM knowledge_items WHERE id=?", (record_id,))
        conn.commit()
        return True
    except Exception as e:
        logger.warning(f"SQLite 删除失败: {e}")
        return False


# ── 内部工具 ──

def _row_to_dict(row: sqlite3.Row) -> dict:
    """将 sqlite3.Row 转为 dict，并反序列化 JSON 字段"""
    d = dict(row)
    # 反序列化 JSON 字段
    for field in ["highlights", "tags"]:
        if field in d and isinstance(d[field], str):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                d[field] = []
    # 布尔字段
    d["actionable"] = bool(d.get("actionable", 0))
    d["embedding_status"] = bool(d.get("embedding_status", 0))
    return d
