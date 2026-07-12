# Personal AI OS — 架构设计

> 最后更新：2026-07-12
> 反映代码实际运行状态。

---

## 一、系统定位

Personal AI OS = 多 Agent 协作系统。六层架构，~45% 完成。

| Agent | 定位 | 状态 |
|-------|------|------|
| Knowledge Agent | 多端采集 → AI 处理 → 结构化知识库 | 🟢 已完工 |
| Career Agent | 简历解析 + JD 匹配 + 全链路投递 | 🟢 已完工 |
| Discovery Agent | 全网搜索发现新内容 | 🟡 已部署但搜索待修 |
| Recommendation Agent | 知识库内部智能推荐 | 🔴 代码完成但未部署 |
| 自动记账 Agent | 已取消/延期 | ❌ |

---

## 二、六层架构全景

```
Layer 6: 推荐层 (Recommendation)     ← 五维打分 + MMR，未部署
Layer 5: 学习层 (Learning)          ← Discovery 全网发现，待修
Layer 4: Agent 层                   ← Knowledge ✅ Career ✅
Layer 3: 知识层 (Knowledge)         ← SQLite 50条 + Chroma + RAG
Layer 2: 处理层 (Processing)        ← OCR + Summary + 19分类
Layer 1: 采集层 (Ingestion)         ← 企微 Worker → 本地 ETL
```

---

## 三、Knowledge Agent — 数据采集与处理（Layer 1-3）

### 3.1 全链路数据流

```
云端（7×24）:
  企微消息 → CF Worker(解密+排队) → D1数据库 → R2图片存储

本地（Mac 开机）:
  cloud_sync 拉取 → 按类型分发 → ETL管道 → 三写存储
```

### 3.2 消息入口

| 入口 | 方案 | 状态 |
|------|------|------|
| 企微自建应用 | CF Worker + D1 + R2 | ✅ 主采集端 |
| 微信客服 | sync_msg API 轮询 | ⚠️ 限流 |
| 手动 CLI | python main.py | ✅ |

### 3.3 ETL 管道

```
ingestion(采集) → summarize(DeepSeek摘要) → structured_format(层级笔记)
                                            ↓
                              ┌─────────────┼─────────────┐
                              ▼             ▼             ▼
                          飞书表格       SQLite(50条)   Chroma向量库
```

### 3.4 知识库存储

| 存储 | 条数 | 用途 |
|------|------|------|
| SQLite knowledge.db | **50 条** | 本地真相源 |
| ChromaDB (ONNX embedding) | **42 条向量** | 语义检索 (384维) |
| 飞书多维表格 | **16 条** | 主展示层 |

**数据来源分布**：text(32) / file(12) / generic(6)

**分类分布**：科技与AI(11) > 职场与创业(10) > 个人成长(8) > 效率方法(6) > 健康与心理(5) > 产品与工具(3) > 其他

---

## 四、Career Agent — 求职匹配（Layer 4）

### 4.1 功能

| 功能 | 命令 | 状态 |
|------|------|------|
| 简历解析 | `bash match.sh -p 简历.pdf` | ✅ |
| 手动JD匹配 | `bash match.sh` | ✅ |
| 自动搜索+匹配+TOP3 | `bash match.sh --search` | ✅ |
| 定时调度 | launchd 每天7:00 | ✅ |

### 4.2 匹配引擎

```
personal_info.md (完整简历) + JD文本
        → DeepSeek Chat API
        → 五维评分(领域30/技能25/经验20/行业15/亮点10)
        → 匹配点 + 差距点 + 建议
```

### 4.3 代码文件

| 文件 | 功能 |
|------|------|
| `src/agents/career_agent.py` | 主控 (match/search/parse三种模式) |
| `src/skills/resume_skill.py` | PDF/文本 → DeepSeek → 结构化JSON |
| `src/skills/match_skill.py` | JD × 简历 → 0-100分 + 理由 |
| `src/skills/job_search_skill.py` | BOSS直聘搜索 (CDP) |
| `src/skills/liepin_search_skill.py` | 猎聘搜索 |
| `src/skills/resume_customize_skill.py` | TOP3简历定制 |
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
│         状态: 🔴 搜索模块故障，待修                         │
└────────────────────────────┬────────────────────────────┘
                             │ 知识缺口信号
                             ▼
┌─────────────────────────────────────────────────────────┐
│              Recommendation Agent (Layer 6)              │
│   知识库→五维打分→MMR精选→生成推荐理由→桌面通知           │
│   内部推荐：从已有知识库选 TOP 5                          │
│   调度: 每天 8:00                                        │
│   状态: 🔴 代码完成但 launchd 未安装                      │
└─────────────────────────────────────────────────────────┘
```

### 5.2 Discovery Agent 流程

```
[1/6] 兴趣画像提取: DeepSeek 扫描知识库50条 → 输出兴趣JSON
[2/6] 搜索词生成:   DeepSeek 基于画像生成搜索查询
[3/6] 全网搜索:     DuckDuckGo + Bing → 去重
[4/6] AI评分:       DeepSeek 评估每篇与画像的相关性
[5/6] 去重:         SQLite 检查是否已推荐过
[6/6] 推送:         桌面通知 / 保存到数据库
```

**已知问题**：
- DeepSeek API 凌晨超时 → 降级为 "分类名 + 最新资讯 2026"
- DuckDuckGo 包已改名 ddgs，Bing 爬虫返回空
- 整个历史仅发现 1 条有效内容

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

**已实现但未部署**：
- 用户反馈追踪 (liked/skipped/clicked)
- 知识缺口分析 → 传递给 Discovery Agent
- 推荐理由生成 (DeepSeek)

### 5.4 代码文件

| 文件 | 功能 |
|------|------|
| `src/agents/discovery_agent.py` | 外部发现主编排 |
| `src/agents/recommendation_agent.py` | 内部推荐主编排 |
| `src/skills/interest_profile_skill.py` | 知识库 → 兴趣画像 |
| `src/skills/career_goal_skill.py` | 职业目标提取 |
| `src/skills/internal_recommendation_skill.py` | 五维打分 + MMR |
| `src/skills/recommendation_skill.py` | Discovery 评分 |
| `src/skills/web_search_skill.py` | 全网搜索 (DuckDuckGo/Bing) |
| `src/skills/delivery_skill.py` | 桌面通知 + 数据保存 |
| `src/knowledge/rag_retriever.py` | RAG 语义检索 |
| `src/knowledge/chroma_store.py` | ChromaDB 向量存储 |

### 5.5 待改造项

| 优先级 | 事项 |
|--------|------|
| P0 | 修复 Discovery 搜索 (DuckDuckGo→ddgs, Bing→新引擎) |
| P0 | 安装 Recommendation Agent launchd |
| P1 | AI 词云画像系统 (替代静态配置) |
| P1 | 企业微信推送推荐结果 |
| P1 | 飞书数据源读取 (表格+文档) |
| P2 | 固定内容源配置 (RSS/豆瓣/公众号) |
| P2 | 书籍片段推荐 |

---

## 六、共享基础设施

| 组件 | 选型 | 说明 |
|------|------|------|
| AI 引擎 | DeepSeek Chat API | 兼容 OpenAI SDK |
| 向量化 | ChromaDB ONNX (all-MiniLM-L6-v2, 384维) | macOS x86_64 兼容，零 PyTorch |
| 本地 OCR | PaddleOCR | 中文识别，必须 Mac |
| 浏览器渲染 | Playwright Chromium | 单例复用 |
| 消息网关 | Cloudflare Worker + D1 + R2 | 7×24 免费 |
| 主展示 | 飞书多维表格 | 结构化笔记 |
| 本地真相源 | SQLite | data/knowledge.db |
| 定时调度 | macOS launchd | Career(7:00) / Discovery(6:00,18:00) |

---

## 七、目录结构

```
knowledge-agent/
├── src/
│   ├── agents/          # 主编排器 (career/discovery/recommendation)
│   ├── skills/          # 可复用技能模块 (25个)
│   ├── knowledge/       # 存储层 (sqlite/chroma/rag)
│   ├── models/          # AI 客户端 (deepseek)
│   ├── web/             # Dashboard
│   └── tests/           # 测试
├── cloudflare-worker/   # CF Worker (企微网关)
├── prompts/             # Prompt 模板 (10个)
├── config/              # 配置 (.env)
├── data/                # 数据 (knowledge.db / chroma_db / job_output)
├── logs/                # 日志
├── match.sh             # 岗位匹配一键启动
├── start_wechat.sh      # 知识同步一键启动
├── start_career_scheduled.sh  # Career 定时任务
└── start_dashboard.sh   # Dashboard 启动
```

---

## 八、GitHub 仓库

| 仓库 | 用途 |
|------|------|
| `caimeiying0402-lab/knowledge-agent` | 全部代码 |
| `caimeiying0402-lab/AIOS` | 共享上下文 (画像/架构/决策/待办) |
