# Knowledge Agent — 进度与后续操作说明

> 最后更新：2026-06-28
> 目标读者：人类开发者 + AI Agent（Codex / Trae / Claude Code）
> 仓库：git@github.com:caimeiying0402-lab/knowledge-agent.git
> 本地路径：/Users/caimeiying/AI-Agent-Lab/knowledge-agent

---

## 一、项目进度总览

基于六层架构（ARCHITECTURE.md），各层完成度：

| 层 | 名称 | 完成度 | 状态 |
|---|------|--------|------|
| 1 | 数据采集层 | 85% | 🟡 核心通路打通，JS渲染网站待解决 |
| 2 | 数据处理层 | 90% | 🟢 v2 完成，19分类体系运行中 |
| 3 | 知识层 | 25% | 🔴 仅飞书多维表格，缺SQLite和向量库 |
| 4 | Agent层 | 30% | 🔴 仅Knowledge Agent，缺Career/Discovery |
| 5 | 学习层 | 0% | 🔴 未开工 |
| 6 | 推荐层 | 0% | 🔴 未开工 |

**已完成（可直接使用）：**
- 文字/URL/图片输入 → DeepSeek AI摘要（19分类）→ 飞书多维表格 全链路
- 企业微信自建应用消息接收（企微成员 → Flask Webhook → ETL）
- 微信客服消息轮询（个人微信 → sync_msg API → ETL，有频率限制）
- PaddleOCR 本地图片识别（零API成本）
- iCloud Drive 文件监听框架

---

## 二、环境速查

```bash
# 激活环境
cd /Users/caimeiying/AI-Agent-Lab/knowledge-agent
source .venv/bin/activate

# 环境变量（所有 API Key 在这里）
cat config/.env

# 运行核心 ETL
PYTHONPATH=src python src/main.py

# 运行全链路测试
PYTHONPATH=src python src/tests/test_harness.py

# 启动企微 Webhook（需要 cloudflared 隧道）
bash start_wechat.sh app

# 启动微信客服轮询（无需隧道，推荐个人微信方案）
bash start_wechat.sh poller

# 启动全部服务
bash start_wechat.sh all
```

**关键依赖：**
```
openai          # DeepSeek API（兼容 OpenAI SDK）
python-dotenv   # 环境变量
requests        # HTTP
beautifulsoup4  # HTML解析
paddleocr       # OCR（本地引擎）
flask           # Webhook 服务
pycryptodome    # 企微消息加解密
Pillow          # 测试图片生成
```

---

## 三、后续任务（按优先级排序）

### P1-1：Headless 浏览器抓取 JS 渲染网站

**问题：** 小红书、公众号等网站内容由 JS 动态渲染，requests + BeautifulSoup 只能拿到空壳 HTML 或 og:metadata。

**目标：** 新增 Playwright 方案，当直接抓取内容不足时自动降级到浏览器渲染。

**涉及文件：**
- 新建：`src/skills/browser_skill.py`
- 修改：`src/skills/ingestion_skill.py`（在 `_ingest_xiaohongshu` 和 `_ingest_wechat_mp` 中添加降级逻辑）
- 修改：`requirements.txt`（添加 `playwright`）

**具体实现步骤：**

#### Step 1: 安装依赖
```bash
source .venv/bin/activate
pip install playwright
playwright install chromium
```
在 `requirements.txt` 末尾添加：
```
playwright
```

#### Step 2: 创建 `src/skills/browser_skill.py`

文件结构：
```python
"""
浏览器渲染抓取技能 — Playwright 方案
用于抓取 JS 动态渲染的网站（小红书、公众号等）
零 API 成本，本地 Chromium 运行
"""

import logging
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

# 单例浏览器实例（复用，避免反复启动）
_browser_instance = None
_playwright_instance = None


def _get_browser():
    """获取或创建浏览器实例（单例模式）"""
    global _browser_instance, _playwright_instance
    if _browser_instance is None:
        _playwright_instance = sync_playwright().start()
        _browser_instance = _playwright_instance.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        logger.info("Playwright Chromium 浏览器已启动")
    return _browser_instance


def render_and_extract(url: str, wait_selector: str = None, timeout: int = 15000) -> str:
    """
    用浏览器渲染页面并提取可见文本。

    Args:
        url: 目标 URL
        wait_selector: 等待某个 CSS 选择器出现后再提取（如 '#detail-desc'）
        timeout: 超时毫秒数

    Returns:
        页面中的可见文本内容
    """
    browser = _get_browser()
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/16.0 Mobile/15E148 Safari/604.1"
        ),
        viewport={"width": 390, "height": 844},
        locale="zh-CN",
    )
    page = context.new_page()

    try:
        page.goto(url, wait_until="networkidle", timeout=timeout)

        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, timeout=5000)
            except Exception:
                logger.debug(f"等待选择器超时: {wait_selector}")

        # 等待额外 2 秒让动态内容完全渲染
        page.wait_for_timeout(2000)

        text = page.inner_text("body")
        context.close()
        return text.strip()
    except Exception as e:
        context.close()
        raise e


def stop_browser():
    """关闭浏览器实例（服务停止时调用）"""
    global _browser_instance, _playwright_instance
    if _browser_instance:
        _browser_instance.close()
        _browser_instance = None
    if _playwright_instance:
        _playwright_instance.stop()
        _playwright_instance = None
```

#### Step 3: 修改 `src/skills/ingestion_skill.py`

在文件顶部 import 区域添加：
```python
from skills.browser_skill import render_and_extract
```

修改 `_ingest_xiaohongshu` 函数：
- 在现有方式1（INITIAL_STATE解析）和方式2（CSS选择器）之后
- 在所有提取逻辑之后、`_build_result` 之前
- 添加降级判断：如果 `len(full_text) < 100`（内容明显不足），尝试 Playwright

具体插入位置：在 `_ingest_xiaohongshu` 函数中，`# 组装内容` 代码块之后、`# 如果只拿到导航文本` 判断之前，插入：

```python
        # ── 方式3：Playwright 浏览器渲染降级 ──
        if len(full_text) < 100:
            try:
                logger.info(f"小红书内容不足({len(full_text)}字)，尝试Playwright渲染...")
                rendered = render_and_extract(
                    url,
                    wait_selector="#detail-desc",
                    timeout=20000,
                )
                if rendered and len(rendered) > len(full_text):
                    body = rendered
                    note_parts = [rendered]
                    logger.info(f"Playwright 渲染成功，获取到 {len(rendered)} 字")
            except Exception as e:
                logger.warning(f"Playwright 渲染失败: {e}")
```

修改 `_ingest_wechat_mp` 函数：
- 在方式1（HTML解析）之后、方式2（og/metadata降级）之前
- 添加：如果 title 和 body 都为空，尝试 Playwright

具体插入位置：在 `if title or body:` 判断的 else 分支（即 HTML 解析完全失败时），添加：

```python
        # ── 方式1.5：Playwright 浏览器渲染 ──
        if not title and not body:
            try:
                logger.info("公众号HTML解析无内容，尝试Playwright渲染...")
                rendered = render_and_extract(
                    url,
                    wait_selector="#js_content",
                    timeout=20000,
                )
                if rendered and len(rendered) > 50:
                    # Playwright 拿到的全文，没有分离标题/正文，用第一行作为标题
                    lines = rendered.strip().split("\n")
                    title = lines[0][:50] if lines else ""
                    body = "\n".join(lines[1:]) if len(lines) > 1 else ""
                    logger.info(f"Playwright 渲染成功: title={title[:30]}, body={len(body)}字")
            except Exception as e:
                logger.warning(f"Playwright 渲染失败: {e}")
```

#### Step 4: 修改 `src/main.py` 的测试代码
在 `if __name__ == "__main__":` 块中添加一个小红书/公众号测试用例。

#### Step 5: 验证
```bash
cd /Users/caimeiying/AI-Agent-Lab/knowledge-agent
source .venv/bin/activate

# 测试小红书 URL（需替换为真实笔记链接）
PYTHONPATH=src python -c "
from skills.ingestion_skill import ingest
result = ingest('https://www.xiaohongshu.com/explore/你的笔记ID')
print(f'platform: {result[\"platform\"]}')
print(f'content length: {len(result[\"raw_content\"])} 字')
print(f'preview: {result[\"raw_content\"][:300]}')
"

# 测试公众号 URL（需替换为真实文章链接）
PYTHONPATH=src python -c "
from skills.ingestion_skill import ingest
result = ingest('https://mp.weixin.qq.com/s/你的文章ID')
print(f'content length: {len(result[\"raw_content\"])} 字')
print(f'preview: {result[\"raw_content\"][:300]}')
"
```

**验收标准：**
- 小红书笔记内容 > 200 字（之前 < 50 字）
- 公众号文章内容 > 500 字（之前只有标题）
- Playwright 启动一次后复用，不反复启停浏览器

---

### P2-1：SQLite 本地知识库

**目标：** 在飞书多维表格之外，建立本地 SQLite 数据库作为离线存储和快速查询后端。

**涉及文件：**
- 新建：`src/skills/sqlite_skill.py`
- 新建：`src/knowledge/sqlite_store.py`（数据库操作层）
- 新建：`src/knowledge/__init__.py`
- 修改：`src/main.py`（在飞书写入后同步写 SQLite）

**具体实现步骤：**

#### Step 1: 创建目录结构
```bash
mkdir -p /Users/caimeiying/AI-Agent-Lab/knowledge-agent/src/knowledge
touch /Users/caimeiying/AI-Agent-Lab/knowledge-agent/src/knowledge/__init__.py
```

#### Step 2: 创建 `src/knowledge/sqlite_store.py`

这个文件负责数据库的创建、表结构管理、CRUD 操作。

数据库文件路径：`/Users/caimeiying/AI-Agent-Lab/knowledge-agent/data/knowledge.db`

表结构设计（与飞书字段对齐，但更适合 SQL 查询）：

```sql
CREATE TABLE IF NOT EXISTS knowledge_items (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,          -- 'xiaohongshu' | 'douban' | 'wechat_mp' | ...
    source_path TEXT,                    -- 原始URL或文件路径
    title TEXT NOT NULL,
    summary TEXT,
    full_content TEXT,
    highlights TEXT,                     -- JSON array stored as text: '["亮点1","亮点2"]'
    tags TEXT,                           -- JSON array stored as text: '["标签1","标签2"]'
    category TEXT,
    source_quality TEXT,                 -- 'high' | 'medium' | 'low'
    actionable INTEGER DEFAULT 0,        -- 0/1 boolean
    created_at INTEGER NOT NULL,         -- Unix timestamp (ms)
    updated_at INTEGER NOT NULL,         -- Unix timestamp (ms)
    embedding_status INTEGER DEFAULT 0   -- 0=未向量化, 1=已向量化
);

CREATE INDEX IF NOT EXISTS idx_category ON knowledge_items(category);
CREATE INDEX IF NOT EXISTS idx_created_at ON knowledge_items(created_at);
CREATE INDEX IF NOT EXISTS idx_source_type ON knowledge_items(source_type);
CREATE INDEX IF NOT EXISTS idx_embedding_status ON knowledge_items(embedding_status);
```

需要实现的方法：
```python
def init_db(db_path: str = None) -> sqlite3.Connection
def insert_item(conn, record: dict) -> bool
def update_item(conn, record_id: str, updates: dict) -> bool
def get_item(conn, record_id: str) -> dict | None
def search_by_keyword(conn, keyword: str, limit: int = 20) -> list[dict]
def search_by_category(conn, category: str, limit: int = 20) -> list[dict]
def search_by_tags(conn, tags: list[str], limit: int = 20) -> list[dict]
def get_recent_items(conn, limit: int = 20) -> list[dict]
def get_unembedded_items(conn, limit: int = 50) -> list[dict]
def mark_embedded(conn, record_id: str) -> bool
def get_stats(conn) -> dict  # 总数、分类分布、来源分布
```

#### Step 3: 创建 `src/skills/sqlite_skill.py`

封装对 `sqlite_store.py` 的调用，提供简化的对外接口：

```python
"""
SQLite Skill — 本地知识库读写
对 sqlite_store 的薄封装，提供面向业务层的接口
"""
```

主要暴露：
- `save_to_sqlite(record: dict) -> bool` — 保存一条知识记录
- `search_knowledge(query: str, limit: int = 20) -> list[dict]` — 全文搜索（LIKE 匹配 title + summary）
- `get_knowledge_stats() -> dict` — 知识库统计信息

#### Step 4: 修改 `src/main.py`

在 `_print_success` 之后，飞书写入成功后，同步写入 SQLite：

```python
# 在 process() 函数中，飞书写入成功之后添加：
try:
    from skills.sqlite_skill import save_to_sqlite
    save_to_sqlite(record)
except Exception as e:
    logger.warning(f"SQLite 写入失败（不影响主流程）: {e}")
```

#### Step 5: 验证
```bash
cd /Users/caimeiying/AI-Agent-Lab/knowledge-agent
source .venv/bin/activate

# 运行一条 ETL 确认写入 SQLite
PYTHONPATH=src python -c "
from main import process
result = process('测试SQLite写入：这是一条知识记录')
print(f'✅ title={result[\"title\"]}')
"

# 验证数据库
PYTHONPATH=src python -c "
from knowledge.sqlite_store import init_db, get_stats, get_recent_items
conn = init_db()
print('统计:', get_stats(conn))
items = get_recent_items(conn, 5)
for item in items:
    print(f'  [{item[\"category\"]}] {item[\"title\"][:40]}')
conn.close()
"
```

**验收标准：**
- `data/knowledge.db` 文件自动创建
- ETL 运行后数据同时写入飞书和 SQLite
- 支持按关键词、分类、标签查询
- SQLite 写入失败不影响飞书主流程（try/except 包裹）

---

### P2-2：Chroma 向量库 + RAG 检索

**目标：** 为知识条目生成 Embedding 向量，存入 Chroma，支持语义检索。

**涉及文件：**
- 新建：`src/knowledge/chroma_store.py`
- 新建：`src/skills/embedding_skill.py`
- 修改：`src/main.py`（飞书写入后触发 embedding）
- 修改：`requirements.txt`（添加 `chromadb`）

**具体实现步骤：**

#### Step 1: 安装依赖
```bash
source .venv/bin/activate
pip install chromadb
```
在 `requirements.txt` 添加：
```
chromadb
```

#### Step 2: 确定 Embedding 方案

**推荐方案：用 DeepSeek API 的 Embedding 接口（已有 API Key，零额外成本）**

DeepSeek Embedding 模型：`deepseek-embed`（如果有），或复用 `deepseek-chat` 模型通过特殊 prompt 提取向量（不推荐）。

**备选方案：使用 BGE 本地模型（零 API 成本，但需要 GPU/内存）**
```bash
pip install sentence-transformers
```
模型：`BAAI/bge-small-zh-v1.5`（中文优化，模型文件约 100MB）

**初期建议：用 DeepSeek Embedding API**
因为 DeepSeek 客户端已配好，无需额外下载模型。如果 DeepSeek 没有独立 Embedding API，则退回到 sentence-transformers 本地模型。

#### Step 3: 创建 `src/knowledge/chroma_store.py`

Chroma 数据存储路径：`/Users/caimeiying/AI-Agent-Lab/knowledge-agent/data/chroma_db/`

```python
"""
Chroma 向量库 — 知识条目 Embedding 存储与语义检索
"""

import chromadb
from chromadb.config import Settings
from pathlib import Path
import json

# Collection 名称
COLLECTION_NAME = "knowledge_items"

# Chroma 持久化路径
CHROMA_PATH = Path(__file__).parent.parent.parent / "data" / "chroma_db"


def get_collection():
    """获取或创建 Chroma collection"""
    client = chromadb.PersistentClient(
        path=str(CHROMA_PATH),
        settings=Settings(anonymized_telemetry=False),
    )
    return client.get_or_create_collection(COLLECTION_NAME)


def add_to_chroma(record: dict, embedding: list[float]) -> bool:
    """将一条知识记录和它的 embedding 向量存入 Chroma"""
    ...

def search_similar(query_embedding: list[float], n_results: int = 10) -> list[dict]:
    """语义相似检索"""
    ...

def delete_from_chroma(record_id: str) -> bool:
    """从向量库删除一条记录"""
    ...
```

重要：Chroma collection 的 metadata 存储字段：
- `title`, `summary`, `category`, `tags`（JSON string）, `source_type`, `source_path`, `created_at`

#### Step 4: 创建 `src/skills/embedding_skill.py`

```python
"""
Embedding Skill — 文本向量化
"""

from models.deepseek_client import get_embedding  # 需先在 deepseek_client.py 中添加

def embed_text(text: str) -> list[float]:
    """对文本生成 Embedding 向量"""
    ...

def embed_record(record: dict) -> list[float]:
    """对知识记录生成 Embedding（拼接 title + summary + tags）"""
    text_parts = [
        record.get("title", ""),
        record.get("summary", ""),
        " ".join(record.get("tags", [])),
    ]
    combined = " ".join(filter(None, text_parts))
    return embed_text(combined)
```

#### Step 5: 扩展 `src/models/deepseek_client.py`

如果 DeepSeek 支持 Embedding API，添加：

```python
def get_embedding(text: str) -> list[float]:
    """获取文本的 Embedding 向量"""
    response = client.embeddings.create(
        model="deepseek-embed",  # 或其他可用模型
        input=text,
    )
    return response.data[0].embedding
```

如果 DeepSeek 没有 Embedding API，则改用 `sentence-transformers`：
```python
# 备选方案：本地 BGE 模型
from sentence_transformers import SentenceTransformer

_embed_model = None

def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        _embed_model = SentenceTransformer("BAAI/bge-small-zh-v1.5")
    return _embed_model

def get_embedding(text: str) -> list[float]:
    model = _get_embed_model()
    return model.encode(text).tolist()
```

#### Step 6: 修改 `src/main.py`

在飞书写入成功后，异步触发 embedding（不阻塞主流程）：

```python
import threading

def _embed_async(record: dict):
    """后台异步生成 embedding 并存入 Chroma"""
    try:
        from skills.embedding_skill import embed_record
        from knowledge.chroma_store import add_to_chroma
        embedding = embed_record(record)
        add_to_chroma(record, embedding)
        logger.info(f"Embedding 完成: {record['title'][:30]}")
    except Exception as e:
        logger.warning(f"Embedding 失败: {e}")

# 在 process() 中飞书写入成功后：
threading.Thread(target=_embed_async, args=(record,), daemon=True).start()
```

#### Step 7: 创建 RAG 检索入口

在 `src/knowledge/` 下创建 `rag_retriever.py`：

```python
"""
RAG 检索器 — 语义搜索知识库
"""

def search(query: str, top_k: int = 10) -> list[dict]:
    """
    语义搜索知识库。

    Args:
        query: 搜索查询文本
        top_k: 返回结果数量

    Returns:
        [
            {
                "title": "...",
                "summary": "...",
                "category": "...",
                "tags": [...],
                "source_path": "...",
                "similarity_score": 0.95,
            },
            ...
        ]
    """
    from skills.embedding_skill import embed_text
    from knowledge.chroma_store import search_similar

    query_embedding = embed_text(query)
    results = search_similar(query_embedding, n_results=top_k)
    return results
```

#### Step 8: 验证
```bash
# 先写入几条知识
PYTHONPATH=src python -c "
from main import process
process('Python是一门优雅的编程语言，在数据科学和AI领域广泛应用')
process('咖啡豆的烘焙程度决定了咖啡的风味，浅烘偏酸深烘偏苦')
process('Claude Code是Anthropic推出的AI编程助手，支持终端操作')
"

# 测试语义搜索
PYTHONPATH=src python -c "
from knowledge.rag_retriever import search
results = search('编程工具')
for r in results:
    print(f'[{r[\"category\"]}] {r[\"title\"]} (score={r.get(\"similarity_score\", 0):.2f})')
"
```

**验收标准：**
- 每条知识入库后自动生成 embedding 向量
- Chroma 持久化存储在 `data/chroma_db/`
- 语义搜索返回相关结果（"编程工具" 能搜到 "Claude Code" 相关内容）
- Embedding 生成失败不影响飞书和 SQLite 写入

---

### P3-1：Career Agent — 岗位匹配引擎

**目标：** 建立简历解析 → 岗位抓取 → 匹配评分的完整 Agent。

**涉及文件（全部新建）：**
- `src/agents/__init__.py`
- `src/agents/career_agent.py`（主控）
- `src/skills/resume_skill.py`（简历解析）
- `src/skills/job_search_skill.py`（岗位搜索）
- `src/skills/match_skill.py`（匹配评分）

**架构：**
```
用户简历（PDF/文本）
    │
    ▼
resume_skill.py → 结构化简历 {skills: [], experience: [], education: ...}
    │
    ▼
job_search_skill.py → 岗位列表（BOSS直聘/猎聘 API 或模拟）
    │
    ▼
match_skill.py → 每个岗位的匹配评分 + 推荐理由
    │
    ▼
飞书多维表格 / SQLite 存储
```

**具体实现（概要）：**

1. **resume_skill.py**：
   - 输入：简历 PDF（用 PyPDF2 或 pdfplumber 提取文本）或纯文本
   - 用 DeepSeek 提取结构化字段：姓名、技能列表、工作经历（公司+职位+时间段）、教育背景、期望薪资、期望城市
   - 输出 JSON

2. **job_search_skill.py**：
   - 方案A：调用 BOSS 直聘公开 API（如有）
   - 方案B：Playwright 模拟搜索 + 解析列表页 + 详情页
   - 输出：岗位列表，每条包含 {title, company, salary, location, tags, description}

3. **match_skill.py**：
   - 用 DeepSeek 对比简历和岗位描述
   - 输出：匹配度（0-100）、匹配点列表、不匹配点列表、建议

**初期建议：先做简历解析 + 手动输入岗位描述做匹配，岗位搜索留到后面。**

---

### P3-2：Discovery Agent — 规则挖掘

**目标：** 从知识库中挖掘规律和模式（如"咖啡知识中深烘豆出现频率最高"）。

**涉及文件：**
- `src/agents/discovery_agent.py`
- `src/skills/rule_mining_skill.py`
- `src/skills/recommendation_skill.py`（可复用）

**核心逻辑：**
1. 从 SQLite 读取所有知识条目
2. 按分类分组，分析标签共现频率
3. 用 DeepSeek 发现跨领域的关联规律
4. 生成"知识地图"和"兴趣洞察"

---

### 第五层 + 第六层：Learning Layer + Recommendation Layer

**依赖：** 需要先完成 P2-1（SQLite）和 P2-2（Chroma），有足够的用户行为数据。

**Learning Layer 核心：**
- 在前端（或微信交互中）记录用户行为：点击、收藏、忽略、转发
- 行为表结构：
```sql
CREATE TABLE user_behaviors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL,
    behavior_type TEXT NOT NULL,  -- 'click' | 'save' | 'ignore' | 'share'
    timestamp INTEGER NOT NULL,
    context TEXT                   -- 可选：当时在做什么
);
```

**Recommendation Layer 核心：**
- 基于用户兴趣标签 + 行为历史 + 知识库内容
- 推荐算法：协同过滤（标签相似度） + 内容推荐（向量相似度）
- 输出：每日推荐摘要（早报形式）

---

## 四、执行顺序建议

```
Phase 1（当前，2-3天）:
  ├── P1-1: Headless 浏览器 → 解决小红书/公众号抓取
  └── P2-1: SQLite 本地库 → 离线存储能力

Phase 2（1-2周）:
  ├── P2-2: Chroma 向量库 → RAG 检索
  └── P3-1: Career Agent → 简历解析 + 匹配

Phase 3（2-4周）:
  ├── P3-2: Discovery Agent → 规则挖掘
  ├── Layer 5: Learning Layer → 用户行为采集
  └── Layer 6: Recommendation Layer → 智能推荐
```

---

## 五、代码规范（AI Agent 务必遵守）

1. **文件结构：** 新 Skill 放 `src/skills/`，知识层放 `src/knowledge/`，Agent 放 `src/agents/`
2. **命名规范：** 文件名 `snake_case.py`，类名 `PascalCase`，函数名 `snake_case`
3. **导入路径：** 所有 import 基于 `PYTHONPATH=src`，即 `from skills.xxx import yyy`
4. **错误处理：** 新增功能用 try/except 包裹，失败不阻塞主流程
5. **日志：** 用 `logging.getLogger(__name__)` 输出关键步骤
6. **环境变量：** 新增配置项加在 `config/.env.example` 中，实际值在 `config/.env`
7. **测试：** 新增模块在 `src/tests/test_harness.py` 中添加测试用例
8. **不破坏已有功能：** 新增代码是增量式的，不要重构已有文件的核心逻辑
9. **单例模式：** 重量级资源（Playwright 浏览器、PaddleOCR 引擎、Embedding 模型）用单例/全局变量复用
10. **异步化：** 耗时的非关键操作（Embedding 生成、浏览器渲染）用 `threading.Thread` 后台执行
