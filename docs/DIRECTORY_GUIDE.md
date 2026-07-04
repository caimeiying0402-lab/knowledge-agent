# knowledge-agent 目录说明

> 最后更新：2026-07-04

## 顶层结构

```
knowledge-agent/
├── cloudflare-worker/    ← Cloudflare Worker（TypeScript, 7×24 消息接收）
├── config/               ← 配置文件（.env, job_filters.yaml）
├── data/                 ← 运行时数据（SQLite, ChromaDB, 输出文件）
├── docs/                 ← 项目文档（架构、规格书、目录说明）
├── logs/                 ← 运行日志
├── prompts/              ← DeepSeek 系统提示词（.txt）
├── scripts/              ← 工具脚本
├── src/                  ← 🎯 核心代码
│   ├── agents/           ← Agent 主编排器
│   ├── knowledge/        ← 知识存储层（SQLite, ChromaDB, RAG）
│   ├── models/           ← AI 模型客户端
│   ├── skills/           ← 可复用技能模块
│   └── web/              ← Dashboard 网站
├── ARCHITECTURE.md       ← 系统架构设计
├── IDEAS.md              ← 想法池（用户维护）
├── NEXT_STEPS.md         ← 下一步计划（AI 维护）
├── ROADMAP.md            ← 进度看板
├── requirements.txt      ← Python 依赖
├── start_wechat.sh       ← 企微服务启动
├── start_dashboard.sh    ← Dashboard 启动
└── start_chrome_cdp.sh   ← 隔离 Chrome 启动（BOSS/猎聘搜索用）
```

---

## src/ 核心代码

### agents/ — Agent 主编排器

| 文件 | 功能 | 对应链路 |
|------|------|---------|
| `career_agent.py` | Job Agent 主控：搜索→匹配→TOP3→定制 | 求职全流程 |
| `discovery_agent.py` | Discovery Agent：兴趣画像→全网搜索→推荐 | 知识发现 |

### skills/ — 技能模块

| 文件 | 功能 | 数据依赖 |
|------|------|---------|
| `match_skill.py` | 简历×JD 匹配评分（0-100） | `personal_info.md` |
| `resume_customize_skill.py` | 个性化简历摘要 + 打招呼语 | `personal_info.md` + JD |
| `job_search_skill.py` | BOSS直聘搜索（CDP + API） | 隔离 Chrome Cookie |
| `liepin_search_skill.py` | 猎聘搜索（CDP 拦截 API） | 隔离 Chrome Cookie |
| `interest_profile_skill.py` | 从知识库提取用户兴趣画像 | SQLite 知识库 |
| `web_search_skill.py` | DuckDuckGo 全网搜索 | — |
| `recommendation_skill.py` | DeepSeek 相关性评分 + 去重 | SQLite |
| `delivery_skill.py` | macOS 桌面通知 + 保存推荐 | SQLite |
| `summary_skill.py` | AI 摘要（19 分类） | DeepSeek |
| `ingestion_skill.py` | 网页/图片/文本内容抓取 | Playwright/PaddleOCR |
| `embedding_skill.py` | 文本向量化 | ONNX/阿里云 |
| `feishu_skill.py` | 飞书多维表格写入 | 飞书 API |
| `browser_skill.py` | Playwright 浏览器单例 | — |
| `cloud_sync_skill.py` | Cloudflare Worker 消息同步 | D1/R2 |

### knowledge/ — 存储层

| 文件 | 功能 |
|------|------|
| `sqlite_store.py` | SQLite 知识库 + 推荐记录 CRUD |
| `chroma_store.py` | ChromaDB 向量存储 + 语义搜索 |
| `rag_retriever.py` | 混合检索（向量 + 关键词） |

### models/ — AI 模型

| 文件 | 功能 |
|------|------|
| `deepseek_client.py` | DeepSeek Chat API（OpenAI 兼容） |

### web/ — Dashboard

| 文件 | 功能 |
|------|------|
| `dashboard.py` | Flask 应用 + API 路由 |
| `templates/dashboard.html` | 单页前端（5 Tab） |
| `static/style.css` | 深色主题样式 |

---

## prompts/ — 提示词

| 文件 | 被谁使用 | 输入 → 输出 |
|------|---------|------------|
| `job_match_prompt.txt` | `match_skill.py` | 个人资料 + JD → 评分 JSON |
| `job_customize_resume_prompt.txt` | `resume_customize_skill.py` | 个人资料 + JD → 简历摘要 + 招呼语 |
| `summary_prompt.txt` | `summary_skill.py` | 网页正文 → 结构化摘要 JSON |
| `interest_profile_prompt.txt` | `interest_profile_skill.py` | 知识库统计 → 兴趣画像 JSON |
| `search_query_prompt.txt` | `discovery_agent.py` | 兴趣画像 → 搜索词列表 JSON |
| `recommendation_prompt.txt` | `recommendation_skill.py` | 搜索结果 + 画像 → 评分 JSON |

---

## 数据流全貌

```
用户消息(企微/手动) → Worker(D1排队)
  → cloud_sync → ETL管道(main.py)
    → ingest(抓取) → summarize(DeepSeek摘要) → format(结构化)
      → 三写: 飞书 + SQLite + ChromaDB

知识库(SQLite+ChromaDB)
  → discovery_agent → DuckDuckGo搜索 → DeepSeek评分 → 推荐推送

隔离Chrome(CDP :9222)
  → career_agent → BOSS/猎聘搜索 → 匹配评分 → TOP3 → 简历定制
```

---

## 外部依赖关系

```
knowledge-agent/
  ├── 依赖外部文档:
  │   └── /Users/caimeiying/AI-Agent-Lab/skills/personal_info.md  ← 个人数据源
  │
  ├── 与 AIOS/ 的关系:
  │   └── AIOS/ = 知识库+决策记录, knowledge-agent/ = 可执行代码
  │
  └── 与 skills/ 的关系:
      └── skills/ = 给AI读的指令文档, src/skills/ = Python代码模块
```
