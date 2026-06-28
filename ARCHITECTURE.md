# Personal AI OS — 架构设计

> **📌 此文件由 Claude Code 管理。** Trae/Codex 请勿直接修改此文件。
> 如需调整架构设计，在 ROADMAP.md 中提交讨论，或通过 Claude Code 发起变更。
>
> 最后更新：2026-06-28

---

## 总体架构（六层）

```
用户输入（文字 / 图片 / URL / 企微消息 / 微信客服）
                │
┌───────────────┴───────────────┐
│  第一层：数据采集层              │  ← 85% 完成
│  ingestion_skill.py           │     JS渲染网站待Playwright方案
│  multimodal_skill.py (OCR)    │
│  wechat_webhook.py / poller   │
│  icloud_skill.py              │
└───────────────┬───────────────┘
                │ raw_content + platform
                ▼
┌───────────────┴───────────────┐
│  第二层：数据处理层              │  ← 90% 完成
│  summary_skill.py (DeepSeek)  │     v2: 19分类+结构化字段
│  parser: BeautifulSoup4       │
│  OCR: PaddleOCR 本地引擎       │
└───────────────┬───────────────┘
                │ Structured Data (8字段)
                ▼
┌───────────────┴───────────────┐
│  第三层：知识层                 │  ← 25% 完成
│  飞书多维表格 ✅                │     SQLite + Chroma 待实现
│  SQLite 本地库 🔴              │
│  Chroma 向量库 🔴              │
└───────────────┬───────────────┘
                │
                ▼
┌───────────────┴───────────────┐
│  第四层：Agent 层              │  ← 30% 完成
│  Knowledge Agent ✅           │     Career + Discovery 待实现
│  Career Agent 🔴              │
│  Discovery Agent 🔴           │
└───────────────┬───────────────┘
                │
                ▼
┌───────────────┴───────────────┐
│  第五层：学习层                 │  ← 0% 完成
│  用户行为采集 + 偏好数据集       │
└───────────────┬───────────────┘
                │
                ▼
┌───────────────┴───────────────┐
│  第六层：推荐层                 │  ← 0% 完成
│  基于标签+行为+知识库的智能推荐   │
└───────────────────────────────┘
```

---

## 各层详细设计

### 第一层：数据采集层

**核心文件：** `src/skills/ingestion_skill.py`

**输入类型与路由：**
- URL（http/https）→ 平台检测 → 专用抓取器或通用抓取器
- 长文本（>500字符或含换行）→ 直接透传
- 本地文件路径 → 按扩展名分发（图片→OCR，txt/md→直接读取）
- 企微自建应用消息 → `wechat_webhook.py` → ETL
- 微信客服消息 → `wechat_kf_poller.py` → ETL

**平台抓取能力矩阵：**

| 平台 | 状态 | 抓取方式 | 说明 |
|------|------|---------|------|
| Wikipedia | ✅ | requests + BS4 | ~62K 字符 |
| 少数派 | ✅ | requests + BS4 | ~1.3K 字符 |
| 36氪 | ✅ | requests + BS4 | 内容 OK |
| 小红书 | ⚠️ | INITIAL_STATE 解析 | JS 渲染，仅元数据 |
| 公众号 | ⚠️ | HTML 解析 + og 降级 | JS 渲染，通常仅标题 |
| 豆瓣 | ❌ | PC版 + 移动版双路径 | 严格反爬 |
| 知乎 | ❌ | — | 403 |
| 百度百科 | ❌ | — | 403 |

**待解决：** P1-1 Headless 浏览器（Playwright）方案可解决小红书和公众号的 JS 渲染问题。

---

### 第二层：数据处理层

**核心文件：**
- `src/skills/summary_skill.py` — DeepSeek AI 摘要引擎
- `src/skills/multimodal_skill.py` — PaddleOCR 本地 OCR
- `prompts/summary_prompt.txt` — 摘要 Prompt（19分类体系）

**输出字段（8个）：**
| 字段 | 类型 | 说明 |
|------|------|------|
| title | string | ≤15字标题 |
| summary | string | 120-200字摘要，三段式结构 |
| highlights | list[str] | 3-5个关键亮点 |
| category | string | 19分类之一 |
| tags | list[str] | 3-5个标签（领域标签+类型标签） |
| source_quality | string | high / medium / low 可信度 |
| actionable | bool | 是否包含可执行操作 |
| date | string | YYYY-MM-DD |

**19分类体系：**
科技与AI / 产品与工具 / 阅读与影视 / 职场与创业 / 投资与商业 /
设计与创意 / 生活与旅行 / 健康与心理 / 教育与学习 / 人文与哲学 /
社会与热点 / 美食与消费 / 人际关系 / 好词好句 / 个人成长 /
效率方法 / 数据与报告 / 趣味与娱乐 / 其他

---

### 第三层：知识层

**当前存储：**
- 飞书多维表格（11字段）— 主存储，已可用
- data/knowledge.db（SQLite）— 待实现 P2-1
- data/chroma_db/（Chroma 向量库）— 待实现 P2-2

**Schema：**
```json
{
  "id": "uuid",
  "source_type": "平台标识",
  "source_path": "原始URL/路径",
  "title": "标题",
  "summary": "摘要",
  "full_content": "完整内容",
  "highlights": ["亮点1", "亮点2"],
  "tags": ["标签1", "标签2"],
  "category": "分类",
  "source_quality": "high|medium|low",
  "actionable": true/false,
  "created_at": "时间戳(ms)",
  "embedding_status": false
}
```

---

### 第四层：Agent 层

**三个 Agent 设计：**

1. **Knowledge Agent（✅ 已实现）**
   - `src/main.py` 为核心，ETL 全链路
   - 调用链：ingest → summarize → feishu
   - 企微/微信客服入口 → 自动触发

2. **Career Agent（🔴 待实现 P3-1）**
   - Skills：Resume Skill（简历解析）、Job Search Skill（岗位搜索）、Match Skill（匹配评分）
   - 输入：简历 PDF/文本 + 岗位描述
   - 输出：匹配度评分 + 推荐理由

3. **Discovery Agent（🔴 待实现 P3-2）**
   - Skills：Rule Mining Skill（规则挖掘）、Recommendation Skill（推荐）
   - 输入：知识库全量数据
   - 输出：跨领域关联规律 + 知识地图

---

### 第五层：学习层

**设计思路：**
- 记录用户行为：点击 / 收藏 / 忽略 / 转发
- 行为数据存入 SQLite 表 `user_behaviors`
- 定期聚合形成 Preference Dataset
- 为推荐层提供训练数据

---

### 第六层：推荐层

**设计思路：**
- 协同过滤：基于标签相似度的内容推荐
- 内容推荐：基于 Embedding 向量相似度的语义推荐
- 输出：每日推荐摘要（类似早报）

---

## 技术栈

| 组件 | 技术选型 | 说明 |
|------|---------|------|
| 语言 | Python 3.12 | .venv 虚拟环境 |
| AI 摘要 | DeepSeek Chat API | 兼容 OpenAI SDK |
| HTML 解析 | BeautifulSoup4 | 多容器选择器 |
| OCR | PaddleOCR | 本地引擎，零 API 成本 |
| 浏览器渲染 | Playwright（计划中）| P1-1 待实现 |
| 主存储 | 飞书多维表格 | 11字段，已可用 |
| 本地存储 | SQLite（计划中）| P2-1 待实现 |
| 向量存储 | Chroma（计划中）| P2-2 待实现 |
| 企微接入 | Flask + Cloudflare Tunnel | 端口 5001 |
| 微信客服 | 企微 sync_msg API 轮询 | 方案 B，无需隧道 |

---

## 文件所有权

| 文件 | 管理者 | 说明 |
|------|--------|------|
| `ARCHITECTURE.md` | **Claude Code** | 架构设计权威文件，Trae 只读 |
| `NEXT_STEPS.md` | Claude Code | 任务拆解和操作说明，Trae 参考 |
| `ROADMAP.md` | **Trae** | 进度跟踪，Claude Code 只读 |
| `README.md` | Trae | 项目说明，随进度更新 |
| `src/` 下所有 `.py` | **Trae** | 代码实现，Claude Code 只读 |
| `prompts/summary_prompt.txt` | 双方 | Prompt 调优需协商 |
| `config/.env.example` | Trae | 新增配置项时更新 |

**协作原则：**
- Claude Code 决定"做什么"（架构方向、功能优先级）
- Trae 决定"怎么做"（代码实现细节、进度推进）
- 双方通过 NEXT_STEPS.md 对齐工作内容
- 如果 Trae 认为架构需要调整，在 ROADMAP.md 中记录讨论点
