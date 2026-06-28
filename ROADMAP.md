# Personal AI OS — 项目进度看板

> **📌 此文件由 Trae 管理。** Claude Code 只读。
> Trae 负责更新各任务的实际进度、完成状态和遇到的问题。
>
> 最后更新：2026-06-28
> 战略文档：`/Users/caimeiying/AI-Agent-Lab/roadmap_matrix.md`

---

## 一、四大 Agent 进度总览

| Agent | 完成度 | 状态 | 下一里程碑 |
|-------|--------|------|-----------|
| Knowledge Agent | ~40% | 🟡 ETL 主链路通，知识库层未建 | SQLite + Chroma + RAG |
| Job Agent | 0% | ⬜ 未启动 | 简历解析 MVP |
| 自动记账 Agent | 0% | ⬜ 未启动 | 账单 CSV 解析 |
| Rule Mining Agent | 0% | ⬜ 未启动 | — |

---

## 二、Knowledge Agent 逐模块进度

### 消息入口

| 模块 | 状态 | 备注 |
|------|------|------|
| 企微自建应用 Webhook | ✅ | Flask :5001 + Cloudflare Tunnel |
| 微信客服轮询 | ⚠️ | sync_msg API，45009 限流，间隔已调到 30s |
| iCloud 文本/URL 监听 | 🟡 | watchdog 框架已写，待配 iPhone 快捷指令 |
| iCloud 图片 → OCR 接线 | 🟡 | 图片移入 inbox 但未接 OCR → summary |
| 微信 SQLite 历史回溯 | 🟡 | 逆向框架已写，待真机联调 |
| 手动 CLI | ✅ | `python src/main.py` |

### 采集 → 处理 → 存储

| 模块 | 状态 | 备注 |
|------|------|------|
| 文字采集 | ✅ | 任意文本透传 |
| 通用网页抓取 | ✅ | Wikipedia/少数派/36氪 可达 |
| 小红书抓取 | ⚠️ | INITIAL_STATE 解析，仅元数据（JS 渲染） |
| 公众号抓取 | ⚠️ | HTML + og 降级，通常仅标题 |
| 豆瓣抓取 | ❌ | 严格反爬 |
| 知乎/百度百科 | ❌ | 403 |
| 图片 OCR | ✅ | PaddleOCR 本地引擎，零成本 |
| AI 摘要 v2 | ✅ | DeepSeek，19 分类 + 8 字段结构化输出 |
| 飞书多维表格 | ✅ | 11 字段自动写入 |

### 知识库层

| 模块 | 状态 | 备注 |
|------|------|------|
| SQLite 本地存储 | 🔴 待实现 | P2 |
| Chroma 向量库 | 🔴 待实现 | P2 |
| RAG 语义检索 | 🔴 待实现 | P2 |
| 用户行为采集 | 🔴 待实现 | P4 |

---

## 三、Job Agent 进度

| 模块 | 状态 | 备注 |
|------|------|------|
| 简历解析 Skill | ⬜ | DeepSeek 结构化提取 |
| JD 采集 Skill | ⬜ | 复用 ingestion |
| 匹配评分 Skill | ⬜ | 语义匹配 + 硬条件 |
| 话术生成 Skill | ⬜ | 个性化打招呼文案 |

---

## 四、自动记账 Agent 进度

| 模块 | 状态 | 备注 |
|------|------|------|
| 账单 CSV 解析 | ⬜ | 支付宝/微信导出格式 |
| 交易分类 | ⬜ | 商户名 → 科目映射 |
| 记账写入 | ⬜ | 随手记无公开 API，核心卡点 |

---

## 五、Rule Mining Agent 进度

| 模块 | 状态 | 备注 |
|------|------|------|
| 行为数据采集 | ⬜ | 点击/收藏/忽略埋点 |
| 规则挖掘引擎 | ⬜ | Apriori/FP-Growth |
| 推荐引擎 | ⬜ | 向量召回 + 规则重排 |

---

## 六、当前待办（按优先级）

| 优先级 | 任务 | 所属 Agent | 负责 |
|--------|------|-----------|------|
| P0 | 配置 iPhone 快捷指令（文本/URL/图片三条） | Knowledge | 用户 + Claude Code |
| P1 | iCloud 图片 → OCR → summary → feishu 接线 | Knowledge | Trae |
| P1 | Headless 浏览器（Playwright） | Knowledge | Trae |
| P2 | SQLite 本地落库 | Knowledge | Trae |
| P2 | Chroma 向量化 + RAG 检索 | Knowledge | Trae |
| P3 | Job Agent MVP（简历解析 + JD 匹配） | Job | Trae |

---

## 七、已知问题

| 问题 | 影响 | 解法 |
|------|------|------|
| 小红书/公众号 JS 渲染 | 内容不完整 | P1 Playwright |
| 微信客服 45009 限流 | poller 停摆 | 增大间隔 or 改用 Webhook |
| 豆瓣/知乎反爬 | 无法自动抓取 | 暂无解法，手动粘贴 |
| 随手记无 API | 记账 Agent 卡点 | 模板导入 or computer-use |

---

## 八、讨论区

> Trae 在此记录架构调整建议或实现中遇到的问题。
> Claude Code 上线后会 Review。

（暂无）
