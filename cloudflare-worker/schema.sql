-- Knowledge Agent Messages D1 Schema
-- 运行: wrangler d1 execute knowledge-agent-messages --file=./schema.sql

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    msg_type TEXT NOT NULL,           -- 'text' | 'link' | 'image' | 'voice'
    from_user TEXT NOT NULL,
    content TEXT,                      -- 文本内容
    url TEXT,                          -- 链接 URL
    title TEXT,                        -- 链接标题
    description TEXT,                  -- 链接描述
    media_id TEXT,                     -- 企微图片 media_id
    image_r2_key TEXT,                 -- R2 对象 key（图片已下载时）
    created_at INTEGER NOT NULL,       -- Unix 时间戳（秒）
    processed INTEGER DEFAULT 0,       -- 0=待处理, 1=已处理
    processed_at INTEGER               -- 处理完成时间戳
);

CREATE INDEX IF NOT EXISTS idx_processed ON messages(processed);
CREATE INDEX IF NOT EXISTS idx_created_at ON messages(created_at);
