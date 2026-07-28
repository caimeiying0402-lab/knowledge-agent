# Personal AI OS — 架构设计

> 最后更新：2026-07-28
> 反映代码实际运行状态。

---

## 一、系统定位

Personal AI OS = 多 Agent 协作系统。六层架构，整体约 **75%** 完成。

| Agent | 定位 | 状态 |
|-------|------|------|
| Knowledge Agent | 多端采集 → AI 处理 → 结构化知识库 | 已完成 |
| Career Agent | 简历解析 + JD 匹配 + 全链路投递 | 已完成 |
| Discovery Agent | 全网搜索发现新内容 | 运行中（~85%） |
| Recommendation Agent | 知识库内部智能推荐 | 运行中（~90%） |
| AI Tutor Agent | 按需导师 + 学习项目 + 人生大学档案 | 设计完成，待开发 |
| 自动记账 Agent | 已取消/延期 | 取消 |
| Rule Mining Agent | 规则挖掘 | 未启动 |

---

## 二、六层架构全景

```
Layer 6: 推荐层 (Recommendation)     ← 五维打分 + MMR，每日8:00运行 ✅
Layer 5: 学习层 (Learning)          ← Discovery 外部发现 + AI Tutor 设计完成
Layer 4: Agent 层                   ← Knowledge✅ Career✅ Discovery~85% Recommendation~90%
Layer 3: 知识层 (Knowledge)         ← SQLite 71条 + Chroma 63向量 + RAG混合检索
Layer 2: 处理层 (Processing)        ← OCR + Summary(v5结构化笔记) + 19分类
Layer 1: 采集层 (Ingestion)         ← 企微 Worker → 本地 ETL
```

---

## 三、Knowledge Agent — 数据采集与处理（Layer 1-3）

### 3.1 全链路数据流

```
云端（7×24）:
  企微消息 → CF Worker(解密+排队) → D1数据库 → R2图片存储

本地（Mac 开机）:
  cloud_sync 拉取 → 按类型分发 → ETL管道 → 四写存储
```

### 3.2 消息入口

| 入口 | 方案 | 状态 |
|------|------|------|
| 企微自建应用 | CF Worker + D1 + R2（自定义域名 wechat.happymia.top） | 主采集端 ✅ |
| 微信客服 | sync_msg API 轮询 | 备用入口 ⚠️ 限流 |
| 手动 CLI | `python main.py` | ✅ |
| 飞书文档导入 | `feishu_import.sh` | ✅ |

### 3.3 ETL 管道（v5）

```
ingestion(采集) → summarize(DeepSeek结构化摘要) → structured_format(编号层级笔记)
                                            ↓
                              ┌─────────────┼─────────────┬─────────────┐
                              ▼             ▼             ▼             ▼
                          飞书表格       SQLite(71条)   Chroma向量库   Obsidian vault
```

**v5 结构化笔记格式**：AI 摘要后，通过 `structured_format_skill.py` 转为用户偏好的编号层级笔记风格，存储在 `full_content` 字段中。飞书展示以结构化笔记为主，保留 `raw_content` 用于回顾。

### 3.4 知识库存储

| 存储 | 条数 | 用途 |
|------|------|------|
| SQLite knowledge.db | **71 条** | 本地真相源 |
| ChromaDB (ONNX embedding, 384维) | **63 条向量** | 语义检索 |
| 飞书多维表格 | 部分同步 | 主展示层 |
| Obsidian vault | 50+ 笔记 | 本地可读知识库 |

**数据来源分布**：text(32) / file(12) / generic(6) / feishu_bitable(15) / feishu_wiki(3) / ai_generated(5)

**分类分布**：科技与AI(17) > 个人成长(12) = 职场与创业(12) > 效率方法(7) > 产品与工具(5) = 健康与心理(5) = 其他(5) > 人际关系(4) > 美食与消费(2) > 技术/编程(1) = 社会与热点(1)

---

## 四、Career Agent — 求职匹配（Layer 4）

### 4.1 功能

| 功能 | 命令 | 状态 |
|------|------|------|
| 简历解析 | `bash match.sh -p 简历.pdf` | ✅ |
| 手动JD匹配 | `bash match.sh` | ✅ |
| 自动搜索+匹配+TOP3 | `bash match.sh --search` | ✅ |
| 定时调度 | launchd 每天 7:00 | ✅ |
| 企微推送结果 | — | ✅ |

### 4.2 匹配引擎

```
personal_info.md (完整简历) + JD文本
        → DeepSeek Chat API
        → 五维评分(领域30/技能25/经验20/行业15/亮点10)
        → 匹配点 + 差距点 + 建议 + 定制化简历摘要 + 打招呼语
```

### 4.3 代码文件

| 文件 | 功能 |
|------|------|
| `src/agents/career_agent.py` | 主控 (match/search/parse三种模式) |
| `src/skills/resume_skill.py` | PDF/文本 → DeepSeek → 结构化JSON |
| `src/skills/match_skill.py` | JD × 简历 → 0-100分 + 理由 |
| `src/skills/job_search_skill.py` | BOSS直聘搜索 (CDP) |
| `src/skills/liepin_search_skill.py` | 猎聘搜索 |
| `src/skills/resume_customize_skill.py` | TOP3简历定制 + 打招呼语 |
| `match.sh` | 一键启动脚本 |

---

## 五、推荐系统（Layer 5-6）

### 5.1 双 Agent 架构

```
┌─────────────────────────────────────────────────────────┐
│                Discovery Agent (Layer 5)                 │
│         兴趣画像 → 搜索词生成 → 全网搜索 → 评分 → 推送    │
│         外部发现：从互联网找新内容                          │
│         调度: 每天 6:00 / 18:00                          │
│         状态: 🟡 运行中，搜索偶有波动（已加重试+RSS补位）   │
└────────────────────────────┬────────────────────────────┘
                             │ 知识缺口信号
                             ▼
┌─────────────────────────────────────────────────────────┐
│              Recommendation Agent (Layer 6)              │
│   知识库→五维打分→MMR精选→生成推荐理由→桌面通知/微信推送   │
│   内部推荐：从已有知识库选 TOP 5                          │
│   调度: 每天 8:00                                        │
│   状态: 🟢 运行中                                         │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│              Daily Digest（每日汇总）                     │
│   Discovery + Recommendation 结果聚合 → 微信/邮件推送      │
│   调度: 每天 8:30（在 Recommendation 之后）               │
└─────────────────────────────────────────────────────────┘
```

### 5.2 Discovery Agent 流程

```
[1/6] 兴趣画像提取: DeepSeek 扫描知识库 → 输出兴趣 JSON
[2/6] 搜索词生成:   DeepSeek 基于画像生成搜索查询
[3/6] 全网搜索:     DuckDuckGo (ddgs) + RSS 固定源 → 去重
[4/6] AI评分:       DeepSeek 评估每篇与画像的相关性
[5/6] 去重:         SQLite 检查是否已推荐过
[6/6] 推送:         桌面通知 / 保存到数据库 / 微信客服推送
```

**已知问题**：
- ddgs 搜索受网络环境影响 → 已加多引擎重试 + RSS 固定源补位
- DeepSeek API 凌晨超时 → 降级为 "分类名 + 最新资讯 2026"

### 5.3 Recommendation Agent 评分算法

```
FINAL_SCORE = 0.40 × 内容相似度(ChromaDB向量)
            + 0.30 × 职业加权(DeepSeek评估)
            + 0.15 × 时间新鲜度(e^{-0.01×days})
            - 0.10 × 互动惩罚(已跳过/已喜欢)
            + 0.05 × MMR多样性加分(贪心精选)
```

**MMR 多样性保证**：
```
对于每个候选: MMR = 0.7×相关性 - 0.3×与已选内容的最大相似度
贪心选择: 逐轮挑出 MMR 最高的条目，保证类别不重复
```

### 5.4 代码文件

| 文件 | 功能 |
|------|------|
| `src/agents/discovery_agent.py` | 外部发现主编排 |
| `src/agents/recommendation_agent.py` | 内部推荐主编排 |
| `src/skills/interest_profile_skill.py` | 知识库 → 兴趣画像 |
| `src/skills/keyword_profile_skill.py` | 关键词画像提取 |
| `src/skills/internal_recommendation_skill.py` | 五维打分 + MMR |
| `src/skills/recommendation_skill.py` | Discovery 评分 |
| `src/skills/web_search_skill.py` | 全网搜索 (DuckDuckGo) |
| `src/skills/delivery_skill.py` | 桌面通知 + 数据保存 |
| `src/skills/daily_digest_skill.py` | 每日汇总聚合 |
| `src/skills/feedback_skill.py` | 用户反馈追踪 |
| `src/knowledge/rag_retriever.py` | RAG 语义检索 |
| `src/knowledge/chroma_store.py` | ChromaDB 向量存储 |

### 5.5 待改造项

| 优先级 | 事项 | 状态 |
|--------|------|------|
| P1 | AI 词云画像系统 | 已有基础 skill，待 Dashboard 可视化 |
| P1 | 微信工作台主动推送推荐结果 | 预留 |
| P1 | 飞书数据源读取（反向同步） | 未启动 |
| P2 | 固定内容源配置化 | `config/content_sources.yaml` 已存在 |
| P2 | 豆瓣书影推荐联动 | `book_recommend_skill.py` 预留 |
| P3 | Rule Mining Agent | 未启动 |

---

## 六、AI Tutor Agent（设计中，待开发）

### 6.1 定位

按需启动的 AI 导师系统，复用 AIOS 底层能力（知识库 + 模型路由 + 数据治理）。

### 6.2 架构

```
用户（网页端）
  → Dispatcher（主控）：路由到对应导师 + 跨导师汇总人生大学档案
    → Mentor Pool（专家池）：ACP导师 / 投资导师 / 亲密关系导师等
      → 每个导师：独立人设 + 知识库 + 项目级记忆
```

### 6.3 关键决策

| 维度 | 决策 |
|------|------|
| 架构 | 主控 Dispatcher + 专家 Agent 池 |
| 资料注入 | 混合策略（硬核手动 / 博主半自动 / 通识免喂） |
| 产出 | 对话 + 进度追踪 + 计划 + 人生大学档案 |
| 生命周期 | 导师长聘 + 学习项目分层 |
| 数据权限 | L1-L4 frontmatter 标注分级体系 |
| 对话介质 | 个人网页（AIOS Dashboard 导师 Tab） |
| 成果落点 | GitHub 仓库（与知识库统一） |
| MVP | α：单导师对话 + ACP 资料 RAG；β：测验/错题本链路 |

### 6.4 设计文档

详见 `docs/AI_TUTOR_DESIGN.md`（2026-07-27，Claude grill-me 完成）。

---

## 七、共享基础设施

| 组件 | 选型 | 说明 |
|------|------|------|
| AI 引擎 | DeepSeek Chat API | 兼容 OpenAI SDK，模型 `deepseek-v4-pro` |
| 向量化 | ChromaDB ONNX (all-MiniLM-L6-v2, 384维) | macOS x86_64 兼容，零 PyTorch |
| 本地 OCR | PaddleOCR | 中文识别，必须 Mac |
| 浏览器渲染 | Playwright Chromium | 单例复用 |
| 消息网关 | Cloudflare Worker + D1 + R2 | 7×24 免费，自定义域名 wechat.happymia.top |
| 主展示 | 飞书多维表格 | 结构化笔记 |
| 本地真相源 | SQLite | `data/knowledge.db` |
| 向量检索 | ChromaDB | `data/chroma_db/` |
| 本地知识库 | Obsidian vault | `vault/` 目录 |
| 定时调度 | macOS launchd | Career(7:00) / Discovery(6:00,18:00) / Recommendation(8:00) |
| Dashboard | Flask + 单页 HTML | `:8501` |
| 模型路由 | CC Switch | assistant.dobest.com / 8001/route / 8090/v1 |

---

## 八、目录结构

```
knowledge-agent/
├── src/
│   ├── agents/          # 主编排器 (career/discovery/recommendation)
│   ├── skills/          # 可复用技能模块 (25+ 个)
│   ├── knowledge/       # 存储层 (sqlite/chroma/rag)
│   ├── models/          # AI 客户端 (deepseek)
│   ├── web/             # Dashboard
│   └── tests/           # 测试
├── cloudflare-worker/   # CF Worker (企微网关)
├── prompts/             # Prompt 模板 (12个)
├── config/              # 配置 (.env, yaml)
├── data/                # 数据 (knowledge.db / chroma_db / job_output)
├── vault/               # Obsidian 知识库
├── logs/                # 日志
├── docs/                # 文档
├── match.sh             # 岗位匹配一键启动
├── start_wechat.sh      # 知识同步一键启动
├── start_career_scheduled.sh  # Career 定时任务
├── start_dashboard.sh   # Dashboard 启动
├── daily_digest.sh      # 每日汇总推送
├── profile.sh           # AI 兴趣画像
└── rag_tune.sh          # RAG 调优工具
```

---

## 九、GitHub 仓库

| 仓库 | 用途 |
|------|------|
| `caimeiying0402-lab/knowledge-agent` | 全部代码 |
| `caimeiying0402-lab/AIOS` | 共享上下文 (画像/架构/决策/待办) |
