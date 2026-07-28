# Personal AI OS — 项目进度看板

> 最后更新：2026-07-28（Claude Code）
> 反映实际完成状态

---

## 一、四大 Agent 进度

| Agent | 完成度 | 状态 | 说明 |
|-------|--------|------|------|
| Knowledge Agent | ~95% | 全链路完成 | ETL + 飞书/SQLite/Chroma/Obsidian 四写 |
| Career Agent | 100% | 完成，每日 7:00 自动运行 | BOSS+猎聘双源，匹配+定制+推送 |
| Discovery Agent | ~85% | 运行中 | ddgs 多引擎搜索 + RSS 固定源，每日 6:00/18:00 |
| Recommendation Agent | ~90% | 运行中，每日 8:00 自动运行 | 五维打分 + MMR 精选 + Daily Digest |
| AI Tutor Agent | 0% | 设计完成 | 见 `docs/AI_TUTOR_DESIGN.md`，待开发 |
| 自动记账 Agent | 0% | 已取消/延期 | — |
| Rule Mining Agent | 0% | 未启动 | — |

---

## 二、Knowledge Agent 逐模块进度

### 采集端

| 模块 | 状态 | 备注 |
|------|------|------|
| 企微 Worker 消息接收 | 已完成 | v9, 7x24, D1+R2, 自定义域名 wechat.happymia.top |
| cloud_sync 本地同步 | 已完成 | 智能轮询, URL自动展开, 图片OCR, 返回值修复 |
| 微信客服轮询 | 备用 | 45009限流，基本不可用 |
| 手动 CLI | 已完成 | `python main.py` |
| 飞书文档导入 | 已完成 | `feishu_import.sh` |

### 处理管道

| 模块 | 状态 | 备注 |
|------|------|------|
| 文字采集 | 已完成 | 含URL自动检测展开 |
| 网页抓取 | 已完成 | 通用 + 小红书/公众号专用 + Playwright 降级 |
| 图片 OCR | 已完成 | PaddleOCR 本地 |
| AI 摘要 | 已完成 | DeepSeek, 19分类, v5结构化笔记 |
| 结构化格式化 | 已完成 | v5, 编号层级笔记风格 |

### 存储 & 检索

| 模块 | 状态 | 备注 |
|------|------|------|
| 飞书多维表格 | 已完成 | 结构化笔记展示 |
| SQLite | 已完成 | 71条, 本地真相源 |
| Chroma 向量库 | 已完成 | 63条向量, ONNX embedding 384维 |
| RAG 检索 | 已完成 | 向量+关键词混合 |
| Obsidian vault | 已完成 | 50+ 笔记，本地可读知识库 |

### 推荐系统 (L4-L6)

| 模块 | 状态 | 备注 |
|------|------|------|
| Discovery Agent | 运行中 | ddgs 多引擎 + RSS 固定源，每日 6:00/18:00 |
| Recommendation Agent | 运行中 | 五维打分 + MMR 精选，每日 8:00 |
| Daily Digest | 已完成 | 汇总推送，微信/邮件兜底 |
| 知识缺口分析 | 已完成 | Recommendation → Discovery 联动 |
| 用户反馈追踪 | 部分完成 | 表结构已建，未充分利用 |

### Career Agent

| 模块 | 状态 |
|------|------|
| 简历解析 | 已完成 |
| BOSS直聘搜索 (CDP) | 已完成 |
| 猎聘搜索 | 已完成 |
| 匹配评分 (5维) | 已完成 |
| 个性化简历生成 | 已完成 |
| 打招呼语生成 | 已完成 |
| 企微推送 | 已完成 |
| 定时调度 (launchd 7:00) | 已完成 |

---

## 三、已知问题

| 问题 | 影响 | 状态 |
|------|------|------|
| ddgs 搜索受网络环境影响 | 部分查询可能返回 0 结果 | 已加重试 + RSS 补位 |
| Bing HTML/Playwright 封锁 | 无法直接抓取 Bing | ddgs 内部已聚合 Bing，无需单独对接 |
| 微信客服 45009 限流 | 备用入口基本不可用 | 主线走企微 Worker |
| ChromaDB collection API 变更 | `list_collections()` 返回对象而非字符串 | 代码已兼容，无影响 |

---

## 四、后续任务

| 优先级 | 任务 | 说明 |
|--------|------|------|
| **P0** | **AI Tutor Agent MVP α** | 单导师对话 + ACP 资料 RAG |
| P1 | AI Tutor Agent MVP β | 测验/进度/错题本链路 |
| P1 | Discovery 搜索稳定性 | 搜索词鲁棒化 + 微信推送 |
| P1 | Recommendation 反馈闭环 | liked/skipped/clicked 充分利用 |
| P1 | AI 词云画像系统 | Dashboard 可视化 |
| P2 | 飞书数据源读取 | 双向同步 |
| P2 | 豆瓣书影推荐联动 | `book_recommend_skill.py` 完善 |
| P3 | Rule Mining Agent | 知识库模式挖掘 |
| P3 | Embedding 升级 | 评估中文 BGE 模型 |
| P3 | Dashboard 增强 | 导师 Tab、画像 Tab、统计 |
