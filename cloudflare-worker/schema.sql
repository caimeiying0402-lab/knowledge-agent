-- Knowledge Agent D1 Schema
-- 运行: wrangler d1 execute knowledge-agent-messages --file=./schema.sql

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    msg_type TEXT NOT NULL,
    from_user TEXT NOT NULL,
    content TEXT,
    url TEXT,
    title TEXT,
    description TEXT,
    media_id TEXT,
    image_r2_key TEXT,
    created_at INTEGER NOT NULL,
    processed INTEGER DEFAULT 0,
    processed_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_processed ON messages(processed);
CREATE INDEX IF NOT EXISTS idx_created_at ON messages(created_at);

-- Discovery Agent 推荐记录表
CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    snippet TEXT,
    score INTEGER DEFAULT 0,
    reason TEXT,
    category TEXT,
    source_query TEXT,
    delivered INTEGER DEFAULT 0,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rec_url ON recommendations(url);
CREATE INDEX IF NOT EXISTS idx_rec_score ON recommendations(score DESC);
CREATE INDEX IF NOT EXISTS idx_rec_created ON recommendations(created_at);
CREATE INDEX IF NOT EXISTS idx_rec_delivered ON recommendations(delivered);

-- AIOS 每日汇总缓存（Mac 推送过来，Web 页面展示）
CREATE TABLE IF NOT EXISTS digests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

-- 用户反馈（Web 页面 like/dislike）
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL,
    action TEXT NOT NULL,
    source TEXT DEFAULT 'web',
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_feedback_item ON feedback(item_id);
CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at);
