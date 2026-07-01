# Personal AI OS — 架构设计（已实现状态）

> 最后更新：2026-07-01
> 反映了代码实际运行状态，非计划状态。

---

## 一、系统定位

Personal AI OS = 多 Agent 协作系统。当前阶段：Knowledge Agent 主线。

| Agent | 定位 | 状态 |
|-------|------|------|
| Knowledge Agent | 多端采集 → AI 处理 → 结构化知识库 → 可检索 | 🟢 主线已完工 |
| Job Agent | 简历 × JD 匹配 | ⬜ 下一阶段 |
| 自动记账 Agent | 账单 → 随手记 | ⬜ 未启动 |
| Rule Mining Agent | 规则挖掘 + 推荐 | ⬜ 未启动 |

---

## 二、Knowledge Agent — 实际架构

### 2.1 全链路数据流

```
企微消息（文字/图片/链接）
       │
       ▼
Cloudflare Worker (v9, 7×24)
  ├─ 签名验证
  ├─ AES-256-CBC 解密（Web Crypto + 纯JS fallback）
  ├─ 图片 → R2 存储（绕过企微3天过期）
  └─ 消息 → D1 排队
       │
       ▼
Mac 本地 cloud_sync_skill.py（手动/定时/后台）
  ├─ 拉取 D1 未处理消息
  ├─ 文字 → URL检测 → 自动展开抓取
  ├─ 图片 → PaddleOCR 本地识别
  └─ 链接 → ingestion_skill 页面抓取
       │
       ▼
ETL 管道 (main.py v5)
  ├─ 1. ingest() — 平台检测 + Playwright 浏览器渲染
  ├─ 2. summarize() — DeepSeek 19分类 + 8字段提取
  ├─ 2.5. structured_format_skill.py — 编号层级笔记格式化
  ├─ 3. write_to_bitable() — 飞书多维表格
  ├─ 4. SQLite 双写 — 本地真相源
  └─ 5. Chroma + ONNX embedding — 向量检索
```

### 2.2 消息入口（当前实际状态）

| 入口 | 技术 | 定位 | 状态 |
|------|------|------|------|
| 企微自建应用 | Cloudflare Worker + D1 + R2 + cloud_sync | **主采集端** | ✅ 全链路通过 |
| 微信客服轮询 | sync_msg API | 备用入口（个人微信） | ⚠️ 45009限流 |
| 手动 CLI | `python main.py` / URL传入 | 调试/批量 | ✅ |

> iCloud + 快捷指令链路已移除（2026-06-28）。企微是唯一采集端。

### 2.3 平台抓取能力

| 平台 | 方案 | 状态 |
|------|------|------|
| 通用网页 | requests + BS4 | ✅ |
| 小红书 | INITIAL_STATE + CSS + Playwright降级 | ✅ |
| 公众号 | HTML + og + Playwright降级 | ✅ |
| 图片 | PaddleOCR 本地识别 | ✅ |

### 2.4 存储层

| 组件 | 用途 | 状态 |
|------|------|------|
| 飞书多维表格 | 主展示（结构化笔记） | ✅ |
| SQLite (`data/knowledge.db`) | 本地真相源，31条 | ✅ |
| Chroma (`data/chroma_db/`) | 向量检索，24条已向量化 | ✅ |
| Cloudflare D1 | 消息排队 | ✅ |
| Cloudflare R2 | 图片暂存 | ✅ |

### 2.5 关键技术细节

**Worker 解密 (cloudflare-worker/src/index.ts v9)**
- Web Crypto API 优先，纯 JS AES-256 兜底
- 非标准 PKCS7 填充（企微大消息用空格填充）→ 使用 msg_len 字段定位
- 自定义域名 `wechat.happymia.top`（workers.dev 国内不可达）

**cloud_sync 智能轮询**
- 有消息 → 30s 快速处理
- 空闲 → 60s 常规轮询
- URL 检测 + ingestion_skill 自动展开

**结构化格式化 (v5)**
- DeepSeek 将摘要转为编号层级笔记
- 每条 ≤80字，无元描述词
- 原文事实不篡改

---

## 三、Job Agent（下一阶段）

简历解析 → 岗位JD采集 → DeepSeek匹配评分 → 飞书/SQLite存储

---

## 四、共享基础设施（已实现）

| 组件 | 选型 |
|------|------|
| AI 引擎 | DeepSeek Chat API |
| OCR | PaddleOCR（本地离线） |
| 浏览器渲染 | Playwright Chromium（单例复用） |
| 消息网关 | Cloudflare Worker + D1 + R2 |
| 主存储 | 飞书多维表格 |
| 本地存储 | SQLite |
| 向量存储 | Chroma + ONNX embedding |
| 语言 | Python 3.12（.venv） |
