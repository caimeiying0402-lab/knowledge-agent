# Personal AI OS — 项目进度看板

> **📌 此文件由 Trae 管理。** Claude Code 只读。
>
> 最后更新：2026-06-28（Trae）
> 战略文档：`/Users/caimeiying/AI-Agent-Lab/roadmap_matrix.md`

---

## 一、四大 Agent 进度总览

| Agent | 完成度 | 状态 | 下一里程碑 |
|-------|--------|------|-----------|
| Knowledge Agent | ~90% | 🟢 全链路已验证（含图片 OCR） | 企微自建应用链路加固 + 百炼 Embedding |
| Job Agent | 0% | ⬜ 未启动 | 简历解析 MVP |
| 自动记账 Agent | 0% | ⬜ 未启动 | 账单 CSV 解析 |
| Rule Mining Agent | 0% | ⬜ 未启动 | — |

---

## 二、Knowledge Agent 逐模块进度

### 消息入口

| 模块 | 状态 | 备注 |
|------|------|------|
| 企微自建应用 Webhook | ✅ | **主采集端**，Flask :5001 + Cloudflare Tunnel，已部署 |
| 微信客服轮询 | ⚠️ | sync_msg API，45009 限流，备用入口 |
| 手动 CLI | ✅ | `PYTHONPATH=src python src/main.py` |

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
| Chroma 向量库 | ✅ | `data/chroma_db/`，ONNX 自动 embedding |
| RAG 语义检索 | ✅ | 向量 + 关键词回退 + 混合模式 |
| Embedding 方案 | ✅ | 百炼 API / ChromaDB ONNX (macOS x86_64 兼容) |
| 数据回填 | ✅ | `scripts/backfill_chroma.py` |
| 用户行为采集 | 🔴 | P4 |

---

## 三、当前待办（按优先级）

| 优先级 | 任务 | 负责 |
|--------|------|------|
| P1 | 企微自建应用链路加固（错误重试、消息回执、健康监控） | Trae |
| P0.5 | 配置阿里云百炼 DashScope API Key（提升中文语义搜索质量） | 用户 |
| ~~P1~~ | ~~iCloud 图片 → OCR → 飞书接线~~ | ✅ |
| ~~P1~~ | ~~Headless 浏览器（Playwright）~~ | ✅ |
| ~~P2~~ | ~~SQLite 本地落库~~ | ✅ |
| ~~P2~~ | ~~Chroma 向量化 + RAG 检索~~ | ✅ |
| ~~P2~~ | ~~Embedding 兼容 macOS x86_64~~ | ✅ |
| P3 | Job Agent MVP | Trae |

---

## 四、讨论区

### 2026-06-28 — 架构修正：iCloud 链路移除

**变更**：iCloud + 快捷指令链路已移除。企微自建应用是唯一主采集端，微信客服轮询为备用入口。
- `icloud_skill.py` 代码保留但不再维护，不在架构中列出
- 移动端采集统一通过企微应用完成

### 2026-06-28 — P2 修复：Embedding macOS x86_64 兼容

**问题**：
- PyTorch 2.2.2 是 macOS x86_64 最高版本，transformers 需要 ≥ 2.4
- DeepSeek 不支持 Embedding API（`deepseek-chat` 无 /embeddings 端点）
- BGE 本地模型（sentence-transformers）因 PyTorch 版本不兼容无法使用

**解决方案**：
- ✅ ChromaDB 内置 ONNX Embedding（all-MiniLM-L6-v2，零 PyTorch 依赖）
- ✅ 阿里云百炼 text-embedding-v4 作为中文优化备选（需配置 DASHSCOPE_API_KEY）
- ✅ chroma_store.py 支持路径备用：`data/chroma_db/` → `~/.cache/knowledge-agent/chroma_db/`
- ✅ 回填脚本 `scripts/backfill_chroma.py`：7条旧数据全部迁移成功
- ✅ 全链路验证通过：ingest → summarize → feishu + sqlite + chroma 三写

**待用户操作**：
- 在 `config/.env` 中添加 `DASHSCOPE_API_KEY=sk-xxx`（百炼控制台获取）
- 这会显著提升中文语义搜索质量（text-embedding-v4 对中文效果远优于 MiniLM）

### 2026-06-28 — P2 完成：SQLite + Chroma + RAG

- ✅ `src/knowledge/sqlite_store.py` + `chroma_store.py` + `rag_retriever.py`
- ✅ `src/skills/sqlite_skill.py` + `embedding_skill.py`
- ✅ `src/main.py` v4：飞书 + SQLite + Chroma 三写 + ONNX 自动 embedding
- ✅ `requirements.txt` 精简（移除 sentence-transformers，macOS x86_64 不兼容）

### 2026-06-28 — P1-1：Playwright 浏览器渲染

- ✅ `src/skills/browser_skill.py` + ingestion 降级逻辑
