# Knowledge Agent — 进度与后续操作说明

> 最后更新：2026-07-28
> 目标读者：人类开发者 + AI Agent（Claude / Codex / Trae）
> 仓库：git@github.com:caimeiying0402-lab/knowledge-agent.git
> 本地路径：/Users/caimeiying/AI-Agent-Lab/knowledge-agent

---

## 一、项目进度总览

Personal AI OS = 多 Agent 协作系统。六层架构，整体约 **75%** 完成。

| 层 | 名称 | 完成度 | 状态 |
|---|------|--------|------|
| 1 | 数据采集层 | 95% | 企微云端链路完成，JS渲染已解决 |
| 2 | 数据处理层 | 90% | v5 结构化笔记格式，19分类体系运行中 |
| 3 | 知识层 | 85% | SQLite 71条 + Chroma 63向量，RAG混合检索可用 |
| 4 | Agent层 | 80% | Knowledge✅ Career✅ Discovery~85% Recommendation~90% |
| 5 | 学习层 | 5% | Discovery Agent 承担部分外部发现功能；AI Tutor Agent 设计完成，待开发 |
| 6 | 推荐层 | 80% | 五维打分+MMR精选，每日8:00自动运行 |

### 四大 Agent 现状

| Agent | 定位 | 状态 | 说明 |
|-------|------|------|------|
| **Knowledge Agent** | 多端采集 → AI处理 → 结构化知识库 | 已完成 | 全链路 ETL，飞书+SQLite+Chroma 三写 |
| **Career Agent** | 简历解析 + JD匹配 + 全链路投递 | 已完成 | 每日7:00自动运行，BOSS/猎聘双源 |
| **Discovery Agent** | 兴趣画像 → 全网搜索 → 内容发现 | 运行中 | ddgs多引擎+RSS固定源，每日6:00/18:00 |
| **Recommendation Agent** | 知识库内部智能推荐 | 运行中 | 五维打分+MMR，每日8:00 |
| **AI Tutor Agent** | 按需启动导师，对话+进度追踪+人生大学档案 | 设计完成 | 见 `docs/AI_TUTOR_DESIGN.md`，待开发 |

### 当前知识库规模

| 存储 | 条数 | 用途 |
|------|------|------|
| SQLite knowledge.db | **71 条** | 本地真相源 |
| ChromaDB (ONNX embedding) | **63 条向量** | 语义检索 (384维) |
| 飞书多维表格 | 部分同步 | 主展示层 |
| Obsidian vault | 50+ 笔记 | 本地可读知识库 |

**分类分布**：科技与AI(17) > 个人成长(12) = 职场与创业(12) > 效率方法(7) > 产品与工具(5) = 健康与心理(5) = 其他(5) > 人际关系(4) > 美食与消费(2) > 技术/编程(1) = 社会与热点(1)

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

# 企微云端同步（从 Cloudflare Worker D1 拉取消息并处理）
PYTHONPATH=src python src/skills/cloud_sync_skill.py

# 启动微信客服轮询（备用入口）
bash start_wechat.sh poller

# 岗位匹配
bash match.sh                      # 手动粘贴 JD
bash match.sh --search             # 自动搜索+匹配+TOP3
bash match.sh -p 简历.pdf          # PDF 简历解析

# 推荐系统试运行
PYTHONPATH=src python -m agents.discovery_agent --dry-run
PYTHONPATH=src python -m agents.recommendation_agent --dry-run

# Dashboard
bash start_dashboard.sh
```

**关键依赖：**
```
openai          # DeepSeek API（兼容 OpenAI SDK）
python-dotenv   # 环境变量
requests        # HTTP
beautifulsoup4  # HTML解析
paddleocr       # OCR（本地引擎）
flask           # Dashboard / Webhook 服务
pycryptodome    # 企微消息加解密
Pillow          # 图片处理
playwright      # Headless 浏览器
chromadb        # 向量库
sentence-transformers  # Embedding 备选
```

---

## 三、后续任务（按优先级排序）

### P0：AI Tutor Agent — 开发

**状态**：设计完成 → 待开发  
**设计文档**：`docs/AI_TUTOR_DESIGN.md`  
**日期**：2026-07-27

**架构**：主控 Dispatcher + 专家 Agent 池
- 导师长聘 + 学习项目分层
- 资料注入：混合策略（官方文档手动 / 博主内容半自动抓取 / 通识免喂）
- 对话介质：个人网页（AIOS Dashboard 内嵌导师 Tab）
- 成果落点：GitHub 仓库（与知识库统一）
- L1-L4 数据权限分级（frontmatter 标注）

**MVP 分阶段**：
- **α 阶段**：单导师对话 + ACP 官方文档 RAG 问答（验证人设注入 + 检索）
- **β 阶段**：测验/进度链路（题库 → 判分 → 错题本 → 自适应教学）

**涉及文件（全部新建）**：
- `src/agents/tutor_agent.py`（主控 dispatcher）
- `src/skills/tutor_skill.py`（导师对话编排）
- `src/skills/mentor_pool.py`（专家池管理）
- `src/web/templates/tutor.html`（导师对话界面）
- `prompts/tutor_system_prompt.txt`（导师人设模板）

---

### P1-1：修复 Discovery Agent 搜索稳定性

**问题**：ddgs 搜索受网络环境影响，部分查询返回 0 结果。Bing HTML/Playwright 封锁。

**当前缓解**：已加多引擎重试 + RSS 固定源补位。

**待优化**：
- 搜索词生成更鲁棒（当 DeepSeek API 凌晨超时时降级）
- 固定内容源配置化（RSS/豆瓣/公众号，从 `config/content_sources.yaml` 读取）
- 微信工作台主动推送推荐结果（当前仅桌面通知 + 保存到 SQLite）

---

### P1-2：Recommendation Agent 部署完善

**状态**：代码完成，每日 8:00 launchd 已配置，运行中。

**待完善**：
- 用户反馈闭环（liked/skipped/clicked 追踪，当前有表结构但未充分利用）
- 知识缺口分析 → 更精准地驱动 Discovery Agent
- 企微推送推荐结果（当前是桌面通知 + 微信客服）
- 飞书数据源读取（将飞书表格/文档反向导入知识库）

---

### P1-3：AI 词云画像系统

**目标**：替代静态 `personal_info.md`，从知识库动态提取用户兴趣画像。

**已有基础**：`src/skills/interest_profile_skill.py` + `src/skills/keyword_profile_skill.py`  
**待做**：Dashboard 可视化词云、画像自动更新（导入新内容后触发）。

---

### P2-1：飞书数据源读取

**目标**：将飞书多维表格和文档作为知识库的数据源（双向同步）。

**当前状态**：单向写入（ETL → 飞书）。  
**需求**：反向读取飞书已有内容，ETL 处理后写入 SQLite/Chroma。

---

### P2-2：豆瓣书影推荐联动

**目标**：Discovery Agent 增加豆瓣读书/电影作为固定内容源。

**已有基础**：`src/skills/book_recommend_skill.py`  
**待做**：抓取豆瓣 RSS/API → 与兴趣画像匹配 → 推荐。

---

### P2-3：Rule Mining Agent

**目标**：从知识库中挖掘规律和模式（如"咖啡知识中深烘豆出现频率最高"）。

**已有基础**：`src/agents/discovery_agent.py` 中部分规则提取逻辑。  
**待做**：独立 Agent，定期扫描知识库，生成交叉领域关联洞察。

---

### P3：基础设施优化

| 优先级 | 事项 | 说明 |
|--------|------|------|
| P3 | Embedding 方案升级 | 当前 ONNX all-MiniLM-L6-v2 (384维)，中文效果一般；评估 BGE 中文模型 |
| P3 | 知识库数据迁移 | 飞书多维表 → 逐步迁移到 GitHub 仓库（frontmatter 标注） |
| P3 | Dashboard 增强 | 当前 5 Tab，可增加导师 Tab、画像 Tab、统计数据 Tab |
| P3 | 成本治理 | 评估各 API 调用量，设置预算告警 |

---

## 四、执行顺序建议

```
Phase 0（已完成 ✅）:
  └── 企微链路云端化 → Cloudflare Worker + D1 + R2，Mac 可关机
  └── Headless 浏览器 → 解决小红书/公众号抓取
  └── SQLite 本地库 + Chroma 向量库 + RAG 检索
  └── Career Agent → 完整求职匹配链路

Phase 1（已完成 ✅）:
  └── Discovery Agent → ddgs多引擎 + RSS 固定源
  └── Recommendation Agent → 五维打分 + MMR 精选 + Daily Digest

Phase 2（当前 🚧）:
  └── AI Tutor Agent → MVP α：单导师对话 + ACP 资料 RAG

Phase 3（规划中）:
  ├── AI Tutor Agent β → 测验/进度/错题本链路
  ├── Discovery Agent 优化 → 搜索稳定性 + 微信推送
  ├── 飞书数据源双向同步
  ├── 豆瓣书影推荐联动
  └── Rule Mining Agent
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
11. **文档同步：** 修改代码后同步更新 ARCHITECTURE.md / ROADMAP.md / DIRECTORY_GUIDE.md / 本文件
