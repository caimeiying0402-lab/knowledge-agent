# Trae 入场指南

> 写给 Trae：项目全貌、分工规则、第一个任务。
> Claude Code 写于 2026-06-28，基于 `/Users/caimeiying/AI-Agent-Lab/roadmap_matrix.md`

---

## 一、这个项目是什么

**Personal AI OS** — 多 Agent 协作系统，围绕四个场景：

| Agent | 定位 | 状态 |
|-------|------|------|
| **Knowledge Agent** | 多端采集 → AI 处理 → 飞书知识库 → 可检索 | 🟡 ETL 主链路通 |
| **Job Agent** | 简历 × JD 匹配 + 打招呼话术 | ⬜ 未启动 |
| **自动记账 Agent** | 支付宝/微信账单 → 随手记科目 | ⬜ 未启动 |
| **Rule Mining Agent** | 行为数据 → 规则挖掘 → 个性化推荐 | ⬜ 未启动 |

**当前阶段：全力建设 Knowledge Agent。** 其余三个 Agent 暂不碰。

**GitHub：** `git@github.com:caimeiying0402-lab/knowledge-agent.git`
**本地：** `/Users/caimeiying/AI-Agent-Lab/knowledge-agent`
**分支：** `main`
**战略文档：** `/Users/caimeiying/AI-Agent-Lab/roadmap_matrix.md`（只读参考，了解全貌用）

### ⚠️ 必须在本地工作，不要用云端

本项目依赖大量本地资源，**不能从 GitHub 全新 clone**。必须直接打开本地已有目录：

| 本地依赖 | 说明 | 云端 clone 拿不到 |
|----------|------|-------------------|
| `config/.env` | DeepSeek/GLM API Key | ❌ gitignored |
| `.venv/` | Python 虚拟环境（含 PaddleOCR 等本地模型） | ❌ gitignored |
| `.paddleocr_cache/` | PaddleOCR 本地模型文件 | ❌ gitignored |
| `data/` | 运行时数据、cursor 文件 | ❌ 本地路径 |

**正确打开方式：** 在 Trae 中打开本地文件夹 `/Users/caimeiying/AI-Agent-Lab/knowledge-agent`，不要 clone。

---

## 二、Knowledge Agent 当前进度

| 模块 | 状态 |
|------|------|
| 文字/URL/图片采集 → AI 摘要 → 飞书入库 | ✅ 全链路通 |
| 企微自建应用消息接收 | ✅ |
| 微信客服轮询 | ⚠️ 45009 限流 |
| iCloud 文件监听 | 🟡 框架已写，待配 iPhone 快捷指令 |
| 小红书/公众号 JS 抓取 | ❌ 仅元数据，你的第一个任务 |
| SQLite 本地存储 | ❌ |
| Chroma 向量检索 | ❌ |

---

## 三、和 Claude Code 的分工

| | Claude Code | Trae（你） |
|---|-------------|-----------|
| **管什么** | 架构设计、方向决策、任务拆解 | 代码实现、进度推进 |
| **写什么** | ARCHITECTURE.md、NEXT_STEPS.md、TRAE_ONBOARDING.md | src/ 全部 .py、ROADMAP.md、README.md |
| **不动什么** | src/ 代码、ROADMAP.md | ARCHITECTURE.md（只读） |
| **协商的** | — | prompts/summary_prompt.txt |

**具体规则：**

1. **你管实现。** NEXT_STEPS.md 告诉你做什么，你决定怎么写。觉得方案有问题，写在 ROADMAP.md 讨论区。

2. **ROADMAP.md 是你的。** 完成任务更新状态和百分比。遇到阻塞记进去。

3. **ARCHITECTURE.md 是我的。** 只读。

4. **代码规范：** 新 Skill → `src/skills/`，知识层 → `src/knowledge/`，Agent → `src/agents/`。增量改动，不破坏已有功能。重量级资源（浏览器、OCR、Embedding模型）用单例复用。

5. **README.md 你来维护。**

---

## 四、快速上手

```bash
# ⚠️ 不要 clone！直接 cd 到本地已有目录
cd /Users/caimeiying/AI-Agent-Lab/knowledge-agent
source .venv/bin/activate
PYTHONPATH=src python src/main.py    # 验证全链路
PYTHONPATH=src python src/tests/test_harness.py  # 跑测试
```

**本地环境已经配好，不需要重新安装依赖或配置 .env。**

**本地可用模型（均在 config/.env 中已配置）：**
- DeepSeek Chat API — AI 摘要（`src/models/deepseek_client.py`）
- GLM (Zhipu) Chat Completions API — 备用/扩展（通过 CC Switch 路由）

**其他关键环境变量：**
- `FEISHU_APP_ID/SECRET/TOKEN/TABLE_ID` — 飞书入库
- `WECOM_CORP_ID/CORP_SECRET` — 企微接入

---

## 五、你的第一个任务：P1 Headless 浏览器

打开 `NEXT_STEPS.md`，找到 **P1-1 章节**，按步骤：

1. `pip install playwright && playwright install chromium`
2. 创建 `src/skills/browser_skill.py`
3. 修改 `src/skills/ingestion_skill.py`（小红书和公众号两处插入 Playwright 降级）
4. 用真实 URL 验证内容长度显著提升

完成后更新 ROADMAP.md，标记完成并 push。

---

## 六、完整文件地图

| 文件 | 谁管 | 说明 |
|------|------|------|
| `ARCHITECTURE.md` | Claude Code | 4 Agent 架构设计 |
| `NEXT_STEPS.md` | Claude Code | P1-P3 详细操作步骤 |
| `TRAE_ONBOARDING.md` | Claude Code | 本文档 |
| `IDEAS.md` | 用户 | 想法池，只读勿改 |
| **─ 以下是你的领域 ─** | | |
| `ROADMAP.md` | **你** | 进度跟踪 |
| `README.md` | **你** | 项目说明 |
| `src/main.py` | **你** | ETL 主流程 |
| `src/skills/*.py` | **你** | 各 Skill 实现 |
| `src/models/*.py` | **你** | API 封装 |
| `src/tests/*.py` | **你** | 测试代码 |
| `src/knowledge/` | **你** | 知识层（SQLite/Chroma/RAG） |
| `src/agents/` | **你** | 其他 Agent（Job/记账/Rule Mining） |
| `prompts/summary_prompt.txt` | 协商 | Prompt 调优 |
| `config/.env.example` | **你** | 环境变量模板 |

---

## 七、工作流

```
1. 读 NEXT_STEPS.md → 了解当前任务
2. 写代码（src/ 下）
3. 本地验证通过
4. 更新 ROADMAP.md
5. git commit & push
6. 遇到架构问题 → ROADMAP.md 讨论区
```
