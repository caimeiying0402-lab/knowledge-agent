# Personal AI OS — 项目进度看板

> 最后更新：2026-07-01（Claude Code）
> 反映实际完成状态

---

## 一、四大 Agent 进度

| Agent | 完成度 | 状态 |
|-------|--------|------|
| Knowledge Agent | ~95% | 🟢 全链路完成 |
| Job Agent | 5% | 🚧 开发规格书已完成，待实现 |
| 自动记账 Agent | 0% | ❌ 已取消/延期 |
| Rule Mining Agent | 0% | ⬜ 未启动 |

---

## 二、Knowledge Agent 逐模块进度

### 采集端

| 模块 | 状态 | 备注 |
|------|------|------|
| 企微 Worker 消息接收 | ✅ | v9, 7×24, D1+R2, 自定义域名 wechat.happymia.top |
| cloud_sync 本地同步 | ✅ | 智能轮询, URL自动展开, 图片OCR |
| 微信客服轮询 | ⚠️ | 备用入口, 45009限流 |
| 手动 CLI | ✅ | `python main.py` |

### 处理管道

| 模块 | 状态 | 备注 |
|------|------|------|
| 文字采集 | ✅ | 含URL自动检测展开 |
| 网页抓取 | ✅ | 通用 + 小红书/公众号专用 |
| 图片 OCR | ✅ | PaddleOCR 本地 |
| AI 摘要 | ✅ | DeepSeek, 19分类 |
| 结构化格式化 | ✅ | v5, 编号层级笔记风格 |

### 存储 & 检索

| 模块 | 状态 | 备注 |
|------|------|------|
| 飞书多维表格 | ✅ | 结构化笔记展示 |
| SQLite | ✅ | 31条, 本地真相源 |
| Chroma 向量库 | ✅ | 24条向量化, ONNX embedding |
| RAG 检索 | ✅ | 向量+关键词混合 |

> iCloud 链路已于 2026-06-28 移除，`icloud_skill.py` 已删除。

---

## 三、当前阶段

| 优先级 | 任务 | 状态 |
|--------|------|------|
| P3-1 | Job Agent 开发 | 🚧 规格书已出 (docs/JOB_AGENT_SPEC.md) |
| P2 | Embedding 修复 | ⏸️ 暂缓 |

### Job Agent 进度

| 模块 | 状态 |
|------|------|
| `resume_profile.json` | ✅ 已生成，待人类review |
| `docs/JOB_AGENT_SPEC.md` | ✅ 完整开发规格书 |
| Phase 1: resume + match | ⬜ 待实现 |
| Phase 2: job search + 反爬 | ⬜ 待实现 |
| Phase 3: resume gen + greeting + delivery | ⬜ 待实现 |
| Phase 4: 定时调度 | ⬜ 待实现 |

## 四、后续

| 优先级 | 任务 |
|--------|------|
| P3-2 | Discovery Agent: 规则挖掘 |
