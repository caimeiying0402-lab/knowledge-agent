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

CREATE TABLE IF NOT EXISTS recommendations (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT,
    snippet TEXT,
    score INTEGER DEFAULT 0,
    reason TEXT,
    category_match TEXT,
    interest_category TEXT,
    source_query TEXT,
    full_content TEXT,
    recommended_at INTEGER NOT NULL,
    delivered INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_rec_score ON recommendations(score DESC);
CREATE INDEX IF NOT EXISTS idx_rec_at ON recommendations(recommended_at DESC);
CREATE INDEX IF NOT EXISTS idx_rec_delivered ON recommendations(delivered);

CREATE TABLE IF NOT EXISTS user_interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL,
    interaction_type TEXT NOT NULL,
    recommended_score REAL,
    recommended_batch_id TEXT,
    context TEXT,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (item_id) REFERENCES knowledge_items(id)
);

CREATE INDEX IF NOT EXISTS idx_interactions_item ON user_interactions(item_id);
CREATE INDEX IF NOT EXISTS idx_interactions_type ON user_interactions(interaction_type);
CREATE INDEX IF NOT EXISTS idx_interactions_created ON user_interactions(created_at);

CREATE TABLE IF NOT EXISTS internal_recommendations (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    score REAL NOT NULL,
    score_breakdown TEXT,
    reason TEXT,
    triggered_by TEXT,
    batch_id TEXT,
    gap_signals TEXT,
    delivered INTEGER DEFAULT 0,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (item_id) REFERENCES knowledge_items(id)
);

CREATE INDEX IF NOT EXISTS idx_internal_rec_item ON internal_recommendations(item_id);
CREATE INDEX IF NOT EXISTS idx_internal_rec_batch ON internal_recommendations(batch_id);
CREATE INDEX IF NOT EXISTS idx_internal_rec_created ON internal_recommendations(created_at);

CREATE TABLE IF NOT EXISTS career_goals_cache (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    goals_json TEXT NOT NULL,
    extracted_at INTEGER NOT NULL,
    source_hash TEXT NOT NULL
);
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

# ── 推荐记录 ──

def insert_recommendation(rec: dict) -> bool:
    """插入一条推荐记录，url+recommended_at 组合去重"""
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO recommendations
               (id, url, title, snippet, score, reason, category_match,
                interest_category, source_query, full_content, recommended_at, delivered)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                rec.get("id", ""),
                rec.get("url", ""),
                rec.get("title", ""),
                rec.get("snippet", ""),
                rec.get("score", 0),
                rec.get("reason", ""),
                rec.get("category_match", ""),
                rec.get("interest_category", ""),
                rec.get("source_query", ""),
                rec.get("full_content", ""),
                rec.get("recommended_at", 0),
                1 if rec.get("delivered") else 0,
            ),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.warning(f"推荐写入失败: {e}")
        return False


def get_recommendations(limit: int = 20, delivered_only: bool = False) -> list[dict]:
    """获取推荐记录，按评分降序"""
    conn = _get_conn()
    if delivered_only:
        rows = conn.execute(
            "SELECT * FROM recommendations WHERE delivered=1 ORDER BY score DESC LIMIT ?",
            (limit,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM recommendations ORDER BY score DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_recommendation_stats() -> dict:
    """推荐统计"""
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0]
    delivered = conn.execute(
        "SELECT COUNT(*) FROM recommendations WHERE delivered=1"
    ).fetchone()[0]
    avg_score = conn.execute(
        "SELECT AVG(score) FROM recommendations"
    ).fetchone()[0] or 0
    by_interest = conn.execute(
        "SELECT interest_category, COUNT(*) as cnt FROM recommendations GROUP BY interest_category ORDER BY cnt DESC"
    ).fetchall()
    return {
        "total": total,
        "delivered": delivered,
        "avg_score": round(avg_score, 1),
        "by_interest": {r["interest_category"]: r["cnt"] for r in by_interest},
    }


def is_url_already_known(url: str) -> bool:
    """检查 URL 是否已在知识库或推荐记录中存在"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT id FROM knowledge_items WHERE source_path=? UNION ALL SELECT id FROM recommendations WHERE url=? LIMIT 1",
        (url, url),
    ).fetchone()
    return row is not None


def mark_recommendation_delivered(rec_id: str) -> bool:
    """标记推荐已推送"""
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE recommendations SET delivered=1 WHERE id=?",
            (rec_id,),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.warning(f"更新推荐状态失败: {e}")
        return False


# ── 内部工具 ──

# ── 用户互动记录 ──

def insert_interaction(interaction: dict) -> bool:
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO user_interactions
               (item_id, interaction_type, recommended_score,
                recommended_batch_id, context, created_at)
               VALUES (?,?,?,?,?,?)""",
            (
                interaction.get("item_id", ""),
                interaction.get("interaction_type", ""),
                interaction.get("recommended_score"),
                interaction.get("recommended_batch_id"),
                interaction.get("context"),
                interaction.get("created_at", 0),
            ),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.warning(f"互动记录写入失败: {e}")
        return False


def get_interactions(item_id: str = None, interaction_type: str = None,
                     limit: int = 50) -> list[dict]:
    conn = _get_conn()
    conditions = []
    params = []
    if item_id:
        conditions.append("item_id=?")
        params.append(item_id)
    if interaction_type:
        conditions.append("interaction_type=?")
        params.append(interaction_type)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = conn.execute(
        f"SELECT * FROM user_interactions {where} ORDER BY created_at DESC LIMIT ?",
        params + [limit],
    ).fetchall()
    return [dict(r) for r in rows]


def get_interaction_stats(days: int = 30) -> dict:
    conn = _get_conn()
    cutoff = int(__import__("time").time()) - days * 86400
    total = conn.execute(
        "SELECT COUNT(*) FROM user_interactions WHERE created_at >= ?", (cutoff,)
    ).fetchone()[0]
    by_type = conn.execute(
        """SELECT interaction_type, COUNT(*) as cnt
           FROM user_interactions WHERE created_at >= ?
           GROUP BY interaction_type""",
        (cutoff,),
    ).fetchall()
    liked = conn.execute(
        """SELECT item_id FROM user_interactions
           WHERE interaction_type='liked' AND created_at >= ?""",
        (cutoff,),
    ).fetchall()
    skipped = conn.execute(
        """SELECT item_id FROM user_interactions
           WHERE interaction_type='skipped' AND created_at >= ?""",
        (cutoff,),
    ).fetchall()
    return {
        "total": total,
        "by_type": {r["interaction_type"]: r["cnt"] for r in by_type},
        "liked_items": [r["item_id"] for r in liked],
        "skipped_items": [r["item_id"] for r in skipped],
    }


def get_recently_recommended_item_ids(days: int = 7) -> set[str]:
    conn = _get_conn()
    cutoff = int(__import__("time").time()) - days * 86400
    rows = conn.execute(
        "SELECT DISTINCT item_id FROM internal_recommendations WHERE created_at >= ?",
        (cutoff,),
    ).fetchall()
    return {r["item_id"] for r in rows}


def get_items_by_ids(item_ids: list[str]) -> list[dict]:
    if not item_ids:
        return []
    conn = _get_conn()
    placeholders = ",".join("?" for _ in item_ids)
    rows = conn.execute(
        f"SELECT * FROM knowledge_items WHERE id IN ({placeholders})",
        item_ids,
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


# ── 内部推荐记录 ──

def insert_internal_recommendation(rec: dict) -> bool:
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO internal_recommendations
               (id, item_id, score, score_breakdown, reason, triggered_by,
                batch_id, gap_signals, delivered, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                rec.get("id", ""),
                rec.get("item_id", ""),
                rec.get("score", 0.0),
                rec.get("score_breakdown", "{}"),
                rec.get("reason", ""),
                rec.get("triggered_by", ""),
                rec.get("batch_id", ""),
                rec.get("gap_signals"),
                rec.get("delivered", 0),
                rec.get("created_at", 0),
            ),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.warning(f"内部推荐写入失败: {e}")
        return False


def get_internal_recommendations(limit: int = 20, batch_id: str = None) -> list[dict]:
    conn = _get_conn()
    if batch_id:
        rows = conn.execute(
            "SELECT * FROM internal_recommendations WHERE batch_id=? ORDER BY score DESC LIMIT ?",
            (batch_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM internal_recommendations ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        if d.get("score_breakdown") and isinstance(d["score_breakdown"], str):
            try:
                d["score_breakdown"] = json.loads(d["score_breakdown"])
            except (json.JSONDecodeError, TypeError):
                d["score_breakdown"] = {}
        if d.get("gap_signals") and isinstance(d["gap_signals"], str):
            try:
                d["gap_signals"] = json.loads(d["gap_signals"])
            except (json.JSONDecodeError, TypeError):
                d["gap_signals"] = None
        results.append(d)
    return results


def get_internal_recommendation_stats() -> dict:
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) FROM internal_recommendations").fetchone()[0]
    delivered = conn.execute(
        "SELECT COUNT(*) FROM internal_recommendations WHERE delivered=1"
    ).fetchone()[0]
    avg_score = conn.execute(
        "SELECT AVG(score) FROM internal_recommendations"
    ).fetchone()[0] or 0
    recent_gaps = conn.execute(
        """SELECT gap_signals FROM internal_recommendations
           WHERE gap_signals IS NOT NULL AND gap_signals != ''
           ORDER BY created_at DESC LIMIT 5"""
    ).fetchall()
    return {
        "total": total,
        "delivered": delivered,
        "avg_score": round(avg_score, 1),
        "recent_gaps": [r["gap_signals"] for r in recent_gaps if r["gap_signals"]],
    }


# ── 职业目标缓存 ──

def upsert_career_goals(goals_json: str, source_hash: str) -> bool:
    conn = _get_conn()
    now = int(__import__("time").time())
    try:
        conn.execute(
            """INSERT INTO career_goals_cache (id, goals_json, extracted_at, source_hash)
               VALUES (1, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
               goals_json=excluded.goals_json,
               extracted_at=excluded.extracted_at,
               source_hash=excluded.source_hash""",
            (goals_json, now, source_hash),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.warning(f"职业目标缓存写入失败: {e}")
        return False


def get_career_goals() -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM career_goals_cache WHERE id=1").fetchone()
    if not row:
        return None
    try:
        return {
            "goals": json.loads(row["goals_json"]),
            "extracted_at": row["extracted_at"],
            "source_hash": row["source_hash"],
        }
    except (json.JSONDecodeError, TypeError):
        return None


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
