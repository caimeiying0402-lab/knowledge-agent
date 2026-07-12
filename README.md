# Personal AI OS — Knowledge Agent

个人知识管理 + AI Agent 系统。微信/企微发消息 → 自动抓取 → AI 摘要 → 飞书知识库。

## 日常使用命令

### 知识同步（企微消息 → 飞书知识库）

```bash
# 一键启动全部服务（云端同步 + 微信客服轮询）
bash start_wechat.sh

# 仅启动云端同步（从 Cloudflare Worker 拉取企微消息）
bash start_wechat.sh sync
```

启动后，Mac 开机状态下持续运行。关机期间消息自动排队到 Cloudflare D1，开机后自动补拉。

### 岗位匹配

```bash
# 手动粘贴 JD（最常用，30 秒出分，无需登录任何网站）
bash match.sh

# 从文件读 JD
bash match.sh -f job_description.txt

# 自动搜索+匹配+TOP3+简历定制（需先启动 Chrome）
bash start_chrome_cdp.sh           # 启动隔离 Chrome，手动登录 BOSS/猎聘
bash match.sh --search             # 自动搜索 → 匹配 → TOP3 → 简历定制+打招呼语
```

### 简历解析

```bash
bash match.sh -p 简历.pdf          # PDF/文本 → 结构化 JSON
```

### 定时任务（已配置 launchd）

| 任务 | 频率 | 说明 |
|------|------|------|
| Career Agent | 每天 7:00 | 自动搜索+匹配+TOP3，每小时检查但每天只跑一次 |
| Discovery Agent | 每天 6:00 / 18:00 | 知识推荐+规则挖掘 |

```bash
# 手动触发定时任务
bash start_career_scheduled.sh
```

### Dashboard

```bash
bash start_dashboard.sh             # 启动本地 Dashboard，浏览器访问 :8501
```

---

## 关于可移植性

这是一个 **Personal AI OS**，为个人使用设计，**不能直接在别人的系统上运行**。

**为什么：**

1. **数据私有** — `personal_info.md` 包含个人简历、工作经历、面试记录
2. **密钥绑定** — `.env` 中的 API Key（DeepSeek、飞书、企微、Cloudflare）都是个人账号
3. **基础设施绑定** — Cloudflare Worker + D1 + R2 部署在你个人的 Cloudflare 账号下
4. **第三方应用** — 飞书多维表格、企微自建应用、微信客服都是你个人的企业应用
5. **路径硬编码** — 部分路径（如 `/Users/caimeiying/`）是 macOS 特定

**可以被复用的部分：**
- 六层架构设计（见 ARCHITECTURE.md）
- 代码框架和 Skill 模式（`src/skills/`）
- Prompt 模板（`prompts/`）
- Cloudflare Worker 代码（`cloudflare-worker/`，改配置即可部署）

换句话说：**架构和代码可以分享，但数据和配置是私人的。** 这就像你的个人日记 app — 别人可以用同一个 app，但里面的内容完全不同。

---

## 当前状态

六层架构，整体约 40% 完成。详见 [ROADMAP.md](./ROADMAP.md)。

## 文件索引

| 文件 | 说明 |
|------|------|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | 架构设计 |
| [ROADMAP.md](./ROADMAP.md) | 进度看板 |
| [NEXT_STEPS.md](./NEXT_STEPS.md) | 后续操作指南 |
| [TRAE_ONBOARDING.md](./TRAE_ONBOARDING.md) | AI Agent 入场指南 |
| [docs/knowledge_schema.md](./docs/knowledge_schema.md) | 知识条目字段定义 |
| [docs/WECHAT_SETUP.md](./docs/WECHAT_SETUP.md) | 企微自建应用接入指南 |
| [docs/WECHAT_KF_SETUP.md](./docs/WECHAT_KF_SETUP.md) | 微信客服接入指南 |
| [match.sh](./match.sh) | 岗位匹配一键启动 |
| [start_wechat.sh](./start_wechat.sh) | 知识同步一键启动 |
