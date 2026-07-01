# Trae 入场指南

> 写给 Trae：项目全貌、分工规则。最后更新 2026-07-01。

---

## 一、项目是什么

**Personal AI OS** — 多 Agent 协作系统。

| Agent | 状态 |
|-------|------|
| Knowledge Agent | 🟢 主线已完工 |
| Job Agent | ⬜ 下一阶段 |
| 自动记账 Agent | ⬜ 未启动 |
| Rule Mining Agent | ⬜ 未启动 |

**GitHub：** `git@github.com:caimeiying0402-lab/knowledge-agent.git`
**本地：** `/Users/caimeiying/AI-Agent-Lab/knowledge-agent`

### ⚠️ 必须在本地工作

本项目依赖本地资源，不能从 GitHub 全新 clone。

| 本地依赖 | 说明 |
|----------|------|
| `config/.env` | API Key（gitignored） |
| `.venv/` | Python 虚拟环境 + PaddleOCR |
| `data/` | 运行时数据 |

**正确做法：** 打开本地文件夹 `/Users/caimeiying/AI-Agent-Lab/knowledge-agent`。

---

## 二、Knowledge Agent 当前状态

| 模块 | 状态 |
|------|------|
| 企微 Worker 消息接收 (v9) | ✅ 7×24 D1+R2 |
| 文字/URL/图片采集 | ✅ |
| AI 摘要 (DeepSeek 19分类) | ✅ |
| 结构化格式化 (v5) | ✅ |
| 飞书 + SQLite + Chroma 三写 | ✅ |
| Playwright 浏览器抓取 | ✅ |
| RAG 语义检索 | ✅ |

> iCloud 链路已移除。企微自建应用是唯一采集端。

---

## 三、快速上手

```bash
cd /Users/caimeiying/AI-Agent-Lab/knowledge-agent
source .venv/bin/activate
PYTHONPATH=src python src/main.py              # 跑 ETL
PYTHONPATH=src python src/skills/cloud_sync_skill.py  # 同步积压消息
```

---

## 四、文件地图

| 文件 | 谁管 | 说明 |
|------|------|------|
| `ARCHITECTURE.md` | Claude Code | 架构设计（已实现状态） |
| `NEXT_STEPS.md` | Claude Code | 任务操作说明 |
| `ROADMAP.md` | — | 进度看板 |
| `src/main.py` | — | ETL 主流程 |
| `src/skills/*.py` | — | 各 Skill |
| `src/knowledge/*.py` | — | SQLite/Chroma/RAG |
| `cloudflare-worker/src/index.ts` | — | Worker 代码 |
| `IDEAS.md` | 用户 | 想法池，勿改 |

---

## 五、当前任务：Job Agent 🚧

详见 **`docs/JOB_AGENT_SPEC.md`** — 完整开发规格书（13页）。

**核心链路：** 简历解析 → BOSS/猎聘搜索 → 匹配评分 → Top3 → 个性化简历+打招呼语 → 企微推送

**实现顺序：**
1. Phase 1: `resume_skill.py` + `match_skill.py` + `career_agent.py`
2. Phase 2: `job_search_skill.py` + 反爬虫（核心难点）
3. Phase 3: `resume_generator` + `greeting` + `delivery`
4. Phase 4: launchd 定时调度

**简历数据：** `src/agents/resume_profile.json`（待人类review）
