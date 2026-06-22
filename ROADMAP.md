# Knowledge Agent — Roadmap

> 最后更新：2026-06-21

## 架构概览

```
输入层（多端采集）
  ├── 企业微信自建应用消息 → Flask :5001 → Cloudflare Tunnel
  ├── 微信客服消息（个人微信用户）→ Flask :5002 → Cloudflare Tunnel  ← 新增
  └── 手动 CLI / API 调用
       ↓
ETL 管道（src/main.py）
  ├── ingestion_skill  → 统一采集（URL/文件/文本/图片）
  │     └── 平台增强：小红书 / 豆瓣 / 公众号 / 通用网页
  ├── multimodal_skill → 图片 OCR（PaddleOCR 本地引擎）
  ├── summary_skill    → DeepSeek 摘要（title/summary/tags/category）
  └── feishu_skill     → 写入飞书多维表格
       ↓
知识库（P2 规划中）
  ├── SQLite 本地落库
  ├── Chroma 向量嵌入
  └── RAG 检索
```

---

## ✅ 已完成

### P0 — 企业微信双通道接入（2026-06-21 完成）

**通道 1：企业微信自建应用**（`wechat_webhook.py`，端口 5001）
- [x] Flask Webhook 接收企微成员消息
- [x] Cloudflare Tunnel 内网穿透（QUIC 协议，稳定不掉线）
- [x] 消息类型：文字（直接摘要）、图片（OCR→摘要）、链接（抓网页内容）
- [x] 全链路验证通过：企微发图 → PaddleOCR → DeepSeek → 飞书入库

**通道 2：微信客服**（个人微信用户接入，`wechat_kf_service.py`，端口 5002）← **新增**
- [x] 接收客服事件推送（POST /wechat/kf/callback）
- [x] 调用 `sync_msg` API 拉取消息内容
- [x] 临时素材下载（图片/文件）
- [x] 复用现有 ETL 管道
- [x] 消息游标持久化（增量拉取，避免重复处理）
- [ ] **待配置**：在企微管理后台填写回调 URL（见 WECHAT_KF_SETUP.md）

### ETL 核心管道
- [x] `src/main.py` — 主流程 ingest → summarize → feishu
- [x] `src/skills/ingestion_skill.py` — URL/文件/文本统一采集，含平台识别
- [x] `src/skills/summary_skill.py` — DeepSeek 摘要
- [x] `src/skills/feishu_skill.py` — 飞书多维表格写入
- [x] `src/skills/multimodal_skill.py` — PaddleOCR 本地 OCR（零费用）

### URL 链接增强（P0.5，2026-06-21 完成）
- [x] 小红书 / 豆瓣 / 微信公众号 / 通用网页自动识别
- [x] 各平台专用内容抓取器
- [x] URL 测试：Wikipedia ✅ / GitHub README ✅ / 36氪 ✅

### 基础设施
- [x] Python 3.12 + .venv
- [x] `config/.env` 环境变量管理（含微信客服新变量）
- [x] `start_wechat.sh` 一键启动双通道服务
- [x] `src/tests/test_harness.py` — 16 条自动化测试全通过
- [x] `WECHAT_SETUP.md` + `WECHAT_KF_SETUP.md` 配置文档

---

## 🔜 下一步

### P1 — 端到端验证微信客服
- [ ] 在企微管理后台获取 `WECOM_KF_OPEN_ID`（客服账号详情页）
- [ ] 配置回调 URL：`https://xxx.trycloudflare.com/wechat/kf/callback`
- [ ] 用个人微信搜索/扫码进入「富婆OS客服」，发送消息测试
- [ ] 验证 ETL 全链路（文字/图片/链接）

### P2 — 本地知识库
- [ ] SQLite 本地落库（所有 ingest 内容双写）
- [ ] Chroma + text-embedding 向量化
- [ ] RAG 检索接口（语义搜索个人知识库）

### P3 — 微信数据源
- [ ] 微信 SQLite 数据库真机读取
- [ ] 聊天记录导入知识库

---

## 🔧 技术决策记录

| 决策 | 选择 | 原因 |
|------|------|------|
| 微信双通道 | 自建应用 + 微信客服 | 自建应用覆盖企微成员；客服覆盖个人微信用户 |
| 内网穿透 | Cloudflare Tunnel（cloudflared） | QUIC 协议，稳定不掉线，免费 |
| OCR 引擎 | PaddleOCR 本地 | 零费用、离线可用、效果不输云服务 |
| ~~阿里云百炼~~ | ❌ 已弃用 | 按量付费消耗快，Key 欠费即失效 |
| AI 摘要 | DeepSeek | 性价比高，中文效果好 |
| 客服消息拉取 | sync_msg API 主动拉取 | 事件通知不含消息体，需主动拉取 |

---

## 文件变更记录（2026-06-21）

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/skills/wechat_kf_service.py` | 新增 | 微信客服 Webhook 服务 |
| `start_wechat.sh` | 更新 | 支持 all/app/kf 三种启动模式 |
| `config/.env` | 更新 | 新增 WECOM_KF_* 变量 |
| `WECHAT_KF_SETUP.md` | 新增 | 微信客服配置指南 |
| `ROADMAP.md` | 新增 | 本文档 |

---

## 环境变量速查

| 变量 | 用途 | 是否必填 |
|------|------|---------|
| `DEEPSEEK_API_KEY` | DeepSeek 摘要 | ✅ |
| `FEISHU_APP_ID/SECRET` | 飞书应用凭证 | ✅ |
| `FEISHU_APP_TOKEN/TABLE_ID` | 飞书多维表格 | ✅ |
| `WECOM_CORP_ID/SECRET/AGENT_ID` | 企业微信自建应用 | ✅（通道1） |
| `WECOM_TOKEN/AES_KEY` | 自建应用回调加解密 | ✅（通道1） |
| `WECOM_KF_OPEN_ID` | 客服账号 ID | ✅（通道2） |
| `WECOM_KF_SECRET` | 客服 Secret | 可选（默认用 CORP_SECRET） |
| `WECOM_KF_TOKEN/AES_KEY` | 客服回调加解密 | ✅（通道2） |
