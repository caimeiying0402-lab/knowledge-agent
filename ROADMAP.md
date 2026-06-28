# Personal AI OS — 项目进度看板

> **📌 此文件由 Trae 管理。** Claude Code 只读。
>
> 最后更新：2026-06-28（Trae）
> 战略文档：`/Users/caimeiying/AI-Agent-Lab/roadmap_matrix.md`

---

## 一、四大 Agent 进度总览

| Agent | 完成度 | 状态 | 下一里程碑 |
|-------|--------|------|-----------|
| Knowledge Agent | ~70% | 🟡 ETL + SQLite + Chroma + RAG 已集成 | 生产验证 & iCloud 接线 |
| Job Agent | 0% | ⬜ 未启动 | 简历解析 MVP |
| 自动记账 Agent | 0% | ⬜ 未启动 | 账单 CSV 解析 |
| Rule Mining Agent | 0% | ⬜ 未启动 | — |

---

## 二、Knowledge Agent 逐模块进度

### 消息入口

| 模块 | 状态 | 备注 |
|------|------|------|
| 企微自建应用 Webhook | ✅ | Flask :5001 + Cloudflare Tunnel |
| 微信客服轮询 | ⚠️ | sync_msg API，45009 限流 |
| iCloud 文本/URL 监听 | 🟡 | 框架已写，待配 iPhone 快捷指令 |
| iCloud 图片 → OCR 接线 | 🟡 | 待接线 |
| 手动 CLI | ✅ | `python src/main.py` |

### 采集 → 处理 → 存储

| 模块 | 状态 | 备注 |
|------|------|------|
| 文字采集 | ✅ | 任意文本透传 |
| 通用网页抓取 | ✅ | Wikipedia/少数派/36氪 |
| 小红书抓取 | ✅ | INITIAL_STATE + CSS + Playwright |
| 公众号抓取 | ✅ | HTML + Playwright + og 降级 |
| 图片 OCR | ✅ | PaddleOCR 本地引擎 |
| AI 摘要 v2 | ✅ | DeepSeek，19 分类 + 8 字段 |
| 飞书多维表格 | ✅ | 11 字段自动写入 |

### 知识库层

| 模块 | 状态 | 备注 |
|------|------|------|
| SQLite 本地存储 | ✅ | `data/knowledge.db`，CRUD + 统计 |
| Chroma 向量库 | ✅ | `data/chroma_db/`，语义检索 |
| RAG 语义检索 | ✅ | 向量 + 关键词回退 + 混合模式 |
| 用户行为采集 | 🔴 | P4 |

---

## 三、当前待办（按优先级）

| 优先级 | 任务 | 负责 |
|--------|------|------|
| P0 | 配置 iPhone 快捷指令 | 用户 + Claude Code |
| P1 | iCloud 图片 → OCR → feishu 接线 | Trae |
| ~~P1~~ | ~~Headless 浏览器（Playwright）~~ | ✅ |
| ~~P2~~ | ~~SQLite 本地落库~~ | ✅ |
| ~~P2~~ | ~~Chroma 向量化 + RAG 检索~~ | ✅ |
| P3 | Job Agent MVP | Trae |

---

## 四、讨论区

### 2026-06-28 — P2 完成：SQLite + Chroma + RAG

- ✅ `src/knowledge/sqlite_store.py` + `chroma_store.py` + `rag_retriever.py`
- ✅ `src/skills/sqlite_skill.py` + `embedding_skill.py`
- ✅ `src/main.py` v3：飞书 + SQLite 双写 + 异步 embedding
- ✅ `requirements.txt` 添加 `chromadb`、`sentence-transformers`
- SQLite 零依赖可用，Chroma/Embedding 需本机 `pip install chromadb`
- Embedding 双方案：DeepSeek API 优先 → 本地 BGE 回退

### 2026-06-28 — P1-1：Playwright 浏览器渲染

- ✅ `src/skills/browser_skill.py` + ingestion 降级逻辑
