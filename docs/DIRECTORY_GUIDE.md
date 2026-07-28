# knowledge-agent 目录说明

> 最后更新：2026-07-28

## 顶层结构

```
knowledge-agent/
├── cloudflare-worker/    ← Cloudflare Worker（TypeScript, 7×24 消息接收）
├── config/               ← 配置文件（.env, job_filters.yaml, content_sources.yaml）
├── data/                 ← 运行时数据（SQLite, ChromaDB, 输出文件）
├── docs/                 ← 项目文档（架构、规格书、目录说明、接入指南）
├── logs/                 ← 运行日志
├── prompts/              ← DeepSeek 系统提示词（.txt）
├── scripts/              ← 工具脚本（如 backfill_chroma.py）
├── src/                  ← 核心代码
│   ├── agents/           ← Agent 主编排器
│   ├── knowledge/        ← 知识存储层（SQLite, ChromaDB, RAG）
│   ├── models/           ← AI 模型客户端
│   ├── skills/           ← 可复用技能模块
│   ├── web/              ← Dashboard 网站
│   └── tests/            ← 测试
├── vault/                ← Obsidian 知识库（Markdown 笔记）
├── ARCHITECTURE.md       ← 系统架构设计
├── DIRECTORY_GUIDE.md    ← 本文件：目录说明
├── IDEAS.md              ← 想法池（用户维护）
├── NEXT_STEPS.md         ← 后续操作指南（AI 维护）
├── README.md             ← 项目首页 / 日常使用速查
├── ROADMAP.md            ← 进度看板
├── TRAE_ONBOARDING.md    ← AI Agent 入场指南
├── requirements.txt      ← Python 依赖
├── daily_digest.sh       ← 每日汇总推送
├── match.sh              ← 岗位匹配一键启动
├── profile.sh            ← AI 兴趣画像查看/生成
├── rag_tune.sh           ← RAG 检索调优工具
├── start_career_scheduled.sh  ← Career 定时任务启动
├── start_chrome_cdp.sh   ← 隔离 Chrome 启动（BOSS/猎聘搜索用）
├── start_dashboard.sh    ← Dashboard 启动
└── start_wechat.sh       ← 企微服务 / 知识同步启动
```

---

## src/ 核心代码

### agents/ — Agent 主编排器

| 文件 | 功能 | 对应链路 |
|------|------|---------|
| `career_agent.py` | Career Agent 主控：简历解析 / 手动匹配 / 搜索+匹配+TOP3 | 求职全流程 |
| `discovery_agent.py` | Discovery Agent：兴趣画像 → 搜索词生成 → 全网搜索 → 评分 → 推送 | 知识发现（每日6:00/18:00） |
| `recommendation_agent.py` | Recommendation Agent：知识库 → 五维打分 → MMR精选 → 推荐理由 → 推送 | 内部推荐（每日8:00） |

### skills/ — 技能模块（25+ 个）

| 文件 | 功能 | 数据依赖 |
|------|------|---------|
| `browser_skill.py` | Playwright 浏览器单例（JS渲染抓取） | — |
| `cloud_sync_skill.py` | Cloudflare Worker 消息同步（D1/R2 → 本地 ETL） | D1/R2 |
| `content_source_skill.py` | 固定内容源管理（RSS/公众号/豆瓣等） | `config/content_sources.yaml` |
| `daily_digest_skill.py` | 每日汇总生成（Discovery + Recommendation 结果聚合） | SQLite |
| `delivery_skill.py` | macOS 桌面通知 + 保存推荐到数据库 | — |
| `embedding_skill.py` | 文本向量化（ONNX / 百炼 API 自动回退） | — |
| `feishu_skill.py` | 飞书多维表格读写 | 飞书 API |
| `ingestion_skill.py` | 网页/图片/文本内容抓取（通用 + 小红书/公众号专用） | Playwright/PaddleOCR |
| `match_skill.py` | 简历×JD 匹配评分（0-100，五维） | `personal_info.md` |
| `multimodal_skill.py` | 多模态处理（图片理解等） | — |
| `obsidian_skill.py` | Obsidian vault 写入（本地 Markdown 知识库） | `vault/` |
| `rag_tuner.py` | RAG 检索调优工具（向量+关键词混合参数优化） | ChromaDB |
| `resume_skill.py` | PDF/文本 → DeepSeek → 结构化简历 JSON | `personal_info.md` |
| `resume_customize_skill.py` | 个性化简历摘要 + 打招呼语生成 | `personal_info.md` + JD |
| `sqlite_skill.py` | SQLite 知识库读写薄封装 | `data/knowledge.db` |
| `structured_format_skill.py` | 结构化格式化：AI摘要 → 编号层级笔记 | — |
| `summary_skill.py` | AI 结构化摘要（19 分类 + 标签 + 质量评估） | DeepSeek |
| `web_search_skill.py` | DuckDuckGo 全网搜索（ddgs 多引擎） | — |
| `wechat_webhook.py` | 企微本地 Webhook（已废弃，调试备用） | — |
| `wechat_kf_poller.py` | 微信客服 sync_msg API 轮询（备用入口） | — |
| `wechat_kf_service.py` | 微信客服消息处理服务 | — |
| `wechat_db_skill.py` | 微信数据库相关操作 | — |

**Career Agent 专用技能：**

| 文件 | 功能 |
|------|------|
| `job_search_skill.py` | BOSS直聘搜索（CDP + API） |
| `liepin_search_skill.py` | 猎聘搜索（CDP 拦截 API） |
| `career_goal_skill.py` | 职业目标提取 |

**Recommendation / Discovery 专用技能：**

| 文件 | 功能 |
|------|------|
| `interest_profile_skill.py` | 从知识库提取用户兴趣画像 |
| `keyword_profile_skill.py` | 关键词画像提取 |
| `internal_recommendation_skill.py` | 五维打分 + MMR 多样性精选 |
| `recommendation_skill.py` | Discovery 外部内容相关性评分 |
| `feedback_skill.py` | 用户反馈追踪（liked/skipped/clicked） |

**内容生成技能：**

| 文件 | 功能 |
|------|------|
| `claude_content_skill.py` | Claude 原创内容生成（AI Tutor 等场景预留） |
| `book_recommend_skill.py` | 豆瓣书影推荐联动（预留） |

### knowledge/ — 存储层

| 文件 | 功能 |
|------|------|
| `sqlite_store.py` | SQLite 知识库 + 推荐记录 CRUD |
| `chroma_store.py` | ChromaDB 向量存储 + 语义搜索（支持主路径/缓存路径回退） |
| `rag_retriever.py` | 混合检索（向量相似度 + 关键词匹配） |

### models/ — AI 模型

| 文件 | 功能 |
|------|------|
| `deepseek_client.py` | DeepSeek Chat API（OpenAI 兼容 SDK） |

### web/ — Dashboard

| 文件 | 功能 |
|------|------|
| `dashboard.py` | Flask 应用 + API 路由（5 Tab：总览/知识库/画像/推荐/设置） |
| `templates/dashboard.html` | 单页前端 |
| `static/style.css` | 深色主题样式 |

---

## prompts/ — 提示词模板

| 文件 | 被谁使用 | 输入 → 输出 |
|------|---------|------------|
| `job_match_prompt.txt` | `match_skill.py` | 个人资料 + JD → 五维评分 JSON |
| `job_customize_resume_prompt.txt` | `resume_customize_skill.py` | 个人资料 + JD → 简历摘要 + 招呼语 |
| `job_resume_prompt.txt` | `resume_skill.py` | PDF/文本 → 结构化简历 JSON |
| `summary_prompt.txt` | `summary_skill.py` | 网页正文 → 结构化摘要 JSON（19分类） |
| `interest_profile_prompt.txt` | `interest_profile_skill.py` | 知识库统计 → 兴趣画像 JSON |
| `keyword_profile_prompt.txt` | `keyword_profile_skill.py` | 知识库内容 → 关键词画像 |
| `search_query_prompt.txt` | `discovery_agent.py` | 兴趣画像 → 搜索词列表 JSON |
| `recommendation_prompt.txt` | `recommendation_skill.py` | 搜索结果 + 画像 → 评分 JSON |
| `internal_recommendation_prompt.txt` | `internal_recommendation_skill.py` | 知识库条目 + 画像 → 五维评分 JSON |
| `content_generation_prompt.txt` | `claude_content_skill.py` | 主题 → AI 原创内容 |
| `career_goal_prompt.txt` | `career_goal_skill.py` | 简历/资料 → 职业目标 JSON |
| `gap_analysis_prompt.txt` | `career_agent.py` | 简历 + JD → 差距分析 |

---

## docs/ — 项目文档

| 文件 | 说明 |
|------|------|
| `AI_TUTOR_DESIGN.md` | AI 导师 Agent 完整设计方案（2026-07-27） |
| `DIRECTORY_GUIDE.md` | 本文件：目录结构说明 |
| `JOB_AGENT_SPEC.md` | Career Agent 开发规格书 |
| `knowledge_schema.md` | 知识条目字段定义 |
| `RAG_TUNING_GUIDE.md` | RAG 检索调优指南 |
| `WECHAT_SETUP.md` | 企微自建应用接入指南 |
| `WECHAT_KF_SETUP.md` | 微信客服接入指南 |

---

## 数据流全貌

```
用户消息(企微/手动) → Worker(D1排队)
  → cloud_sync → ETL管道(main.py)
    → ingest(抓取) → summarize(DeepSeek摘要) → structured_format(编号层级笔记)
      → 三写: 飞书表格 + SQLite + ChromaDB + Obsidian vault

知识库(SQLite+ChromaDB)
  → discovery_agent → 兴趣画像 → DuckDuckGo搜索 → DeepSeek评分 → 推送
  → recommendation_agent → 五维打分 → MMR精选 → 推荐理由 → 推送

隔离Chrome(CDP :9222)
  → career_agent → BOSS/猎聘搜索 → 匹配评分 → TOP3 → 简历定制
```

---

## 外部依赖关系

```
knowledge-agent/
  ├── 依赖外部文档:
  │   └── /Users/caimeiying/AI-Agent-Lab/skills/personal_info.md  ← 个人数据源（简历）
  │
  ├── 与 AIOS/ 的关系:
  │   └── AIOS/ = 知识库+决策记录, knowledge-agent/ = 可执行代码
  │
  └── 与 skills/ 的关系:
      └── skills/ = 给AI读的指令文档, src/skills/ = Python代码模块
```
