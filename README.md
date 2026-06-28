# Personal AI OS — Knowledge Agent

个人知识管理 + AI Agent 系统。微信/企微发消息 → 自动抓取 → AI 摘要 → 飞书知识库。

## 快速开始

```bash
cd /Users/caimeiying/AI-Agent-Lab/knowledge-agent
source .venv/bin/activate
cp config/.env.example config/.env  # 编辑填入 API Key
PYTHONPATH=src python src/main.py
```

## 当前状态

六层架构，整体约 40% 完成。详见 [ROADMAP.md](./ROADMAP.md)。

## 文件索引

| 文件 | 说明 |
|------|------|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | 架构设计（Claude Code 维护） |
| [ROADMAP.md](./ROADMAP.md) | 进度看板（Trae 维护） |
| [NEXT_STEPS.md](./NEXT_STEPS.md) | 后续操作指南 |
| [TRAE_ONBOARDING.md](./TRAE_ONBOARDING.md) | Trae 入场指南 |
| [knowledge_schema.md](./knowledge_schema.md) | 知识条目字段定义 |

## 协作分工

| 领域 | 负责 |
|------|------|
| 架构设计、方向决策 | Claude Code |
| 代码实现、进度推进 | Trae |
| 架构文档 (ARCHITECTURE.md) | Claude Code |
| 进度看板 (ROADMAP.md) | Trae |
| 代码 (src/) | Trae |
