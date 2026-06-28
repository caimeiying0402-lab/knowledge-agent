# Trae 入场指南

> 写给 Trae：你要做什么、怎么开始、和 Claude Code 怎么分工。
> Claude Code 写于 2026-06-28。

---

## 一、这个项目是什么

**Personal AI OS**（又名 Knowledge Agent），一个个人知识管理 + AI Agent 系统。

核心功能：用户通过微信/企微发文字、图片、链接 → 自动抓取内容 → AI 提取摘要和标签 → 存入飞书多维表格 → 未来支持语义检索和智能推荐。

**GitHub：** `git@github.com:caimeiying0402-lab/knowledge-agent.git`
**本地：** `/Users/caimeiying/AI-Agent-Lab/knowledge-agent`
**分支：** `main`

---

## 二、当前进度速览

六层架构，目前处于早期阶段：

| 层 | 完成度 | 一句话 |
|---|--------|--------|
| 采集 | 85% | 文字/URL/图片/企微都能进，但小红书和公众号被 JS 渲染卡住 |
| 处理 | 90% | DeepSeek 摘要 v2 很稳，19 分类 + 8 字段结构化输出 |
| 知识 | 25% | 只有飞书多维表格，缺本地库和向量库 |
| Agent | 30% | 只有 Knowledge Agent，Career/Discovery 还没影 |
| 学习 | 0% | — |
| 推荐 | 0% | — |

---

## 三、你要做什么

按优先级，你的第一个任务是 **P1-1：Headless 浏览器**。完成后再推进 P2-1、P2-2。

**详细的操作步骤在 `NEXT_STEPS.md`**，里面写了精确的文件路径、函数签名、代码片段、验证命令。你不需要自己设计方案，照着 NEXT_STEPS.md 实现即可。

---

## 四、和 Claude Code 的分工

**非常重要：我们各管一摊，互不干扰。**

| | Claude Code | Trae（你） |
|---|-------------|-----------|
| **管什么** | 架构设计、方向决策 | 代码实现、进度推进 |
| **写什么文件** | ARCHITECTURE.md、NEXT_STEPS.md | src/ 下所有 .py、ROADMAP.md |
| **不动什么** | src/ 下的 .py 代码 | ARCHITECTURE.md（只读） |
| **协商的** | — | prompts/summary_prompt.txt |

**具体规则：**

1. **你管实现，我管设计。** NEXT_STEPS.md 告诉你做什么，你决定怎么写代码。你觉得设计方案有问题，在 ROADMAP.md 的"讨论区"写下来，我会来 Review。

2. **ROADMAP.md 是你的。** 每完成一个任务，更新状态和完成度百分比。遇到阻塞问题也记进去。

3. **ARCHITECTURE.md 是我的。** 你只读不写。如果架构改了，我会自己更新。

4. **代码在 src/ 下。** 新增 Skill 放 `src/skills/`，知识层放 `src/knowledge/`，Agent 放 `src/agents/`。

5. **不破坏已有功能。** 你的改动是增量的。现有代码（main.py、ingestion_skill.py、summary_skill.py 等）可以修改但必须保持向后兼容。

6. **README.md 随进度更新。** 项目说明文档你来维护。

---

## 五、快速上手

```bash
# 1. 克隆仓库
git clone git@github.com:caimeiying0402-lab/knowledge-agent.git
cd knowledge-agent

# 2. 创建虚拟环境
python3.12 -m venv .venv
source .venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
cp config/.env.example config/.env
# 编辑 config/.env，填入真实 API Key

# 5. 验证环境
PYTHONPATH=src python src/main.py

# 6. 跑测试
PYTHONPATH=src python src/tests/test_harness.py
```

**关键环境变量（config/.env）：**
- `DEEPSEEK_API_KEY` — AI 摘要（必填）
- `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_APP_TOKEN` / `FEISHU_TABLE_ID` — 飞书（测试用）
- `WECOM_CORP_ID` / `WECOM_CORP_SECRET` — 企微（可选，Webhook 用）

---

## 六、你的第一个任务：P1-1 Headless 浏览器

打开 `NEXT_STEPS.md`，找到 **P1-1 章节**，按步骤执行：

1. 安装 Playwright → `pip install playwright && playwright install chromium`
2. 创建 `src/skills/browser_skill.py`（代码在 NEXT_STEPS.md 里有）
3. 修改 `src/skills/ingestion_skill.py`（插入位置和代码都有标注）
4. 验证：用小红书和公众号 URL 测试，确认内容长度大幅提升

做完后：
- 更新 `ROADMAP.md`，把 P1-1 标记为 ✅ 完成
- 更新各层完成度百分比
- 提交代码并 push

---

## 七、Key Files Map

| 文件 | 谁管 | 干什么 |
|------|------|--------|
| `ARCHITECTURE.md` | Claude Code | 架构设计权威文档 |
| `NEXT_STEPS.md` | Claude Code | 任务拆解和操作指南 |
| `ROADMAP.md` | **你** | 进度跟踪 |
| `README.md` | **你** | 项目说明 |
| `IDEAS.md` | **用户（caimeiying）** | 想法池，只读勿改 |
| `TRARE_ONBOARDING.md` | Claude Code | 本文档，你的入场指南 |
| `src/main.py` | **你** | ETL 主流程 |
| `src/skills/*.py` | **你** | 各 Skill 实现 |
| `src/models/*.py` | **你** | API 调用封装 |
| `src/tests/*.py` | **你** | 测试代码 |
| `prompts/summary_prompt.txt` | 协商 | DeepSeek Prompt |
| `config/.env.example` | **你** | 环境变量模板 |

---

## 八、工作流建议

```
1. 阅读 NEXT_STEPS.md 了解下一个任务
2. 实现代码（src/ 下）
3. 本地验证通过
4. 更新 ROADMAP.md（标记完成、更新百分比）
5. 更新 README.md（如果项目面貌有变化）
6. git commit & push
7. 如果遇到架构问题 → 写在 ROADMAP.md 讨论区
```

---

开始吧。有问题写在 ROADMAP.md 讨论区，Claude Code 下次上线会看。
