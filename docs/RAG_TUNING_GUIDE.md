# RAG 调优指南

## 一句话总结

RAG 质量 = 分块质量 × 检索质量。分块决定"能找到什么"，检索决定"找到的是不是你要的"。两个环节都需要人类判断效果并调参。

---

## 快速开始

```bash
cd /Users/caimeiying/AI-Agent-Lab/knowledge-agent

# 1. 看有哪些文档
bash rag_tune.sh list

# 2. 看分块效果（3种策略并排对比）
bash rag_tune.sh chunk 杂谈经验

# 3. 测试检索
bash rag_tune.sh search 月结流程复杂

# 4. 对比不同 chunk_size 的检索差异
bash rag_tune.sh compare 月结

# 5. 查看当前用于 RAG 的用户画像
bash rag_tune.sh profile
```

---

## RAG 流水线（人类调优的5个环节）

```
飞书文档 ──→ [分块] ──→ [向量化] ──→ ChromeDB
                                          │
用户画像 ──→ [构造查询] ──→ [检索] ──→ [重排] ──→ 邮件回顾
                                           │
                                     ← 人类评估 ←
```

### 环节1：分块策略

**你能调的参数：**

| 参数 | 位置 | 说明 |
|------|------|------|
| chunk_size | `rag_tuner.py` → `chunk_by_paragraphs(max_chunk_size=800)` | 目标 chunk 大小，越大上下文越完整但检索精度越低 |
| 分块策略 | L1(固定长度) / L2(按段落) | 默认 L2，你的文档空行少时效果不佳 |
| 标题识别 | `looks_like_heading` 判断条件 | <60字且无句号结尾的行视为标题 |

**怎么判断分块好坏：**
- 每个 chunk 应该是一个**语义完整**的段落或小节
- 不应该在句子中间切断
- 标题和它的内容内容不应该被拆到不同 chunk
- 你的文档如果空行很少 → 分块会产生超大的 chunk → **建议在飞书里加空行**（最根本的解决办法）

**你的文档现状：**
```
杂谈经验:  13048字 → L2分块产生9个chunk，其中1个9605字（"学习知识"整节无空行）
AI学习:    33724字 → 同理
财务笔记:  12057字 → 同理
```

### 环节2：检索查询构造

**查询来源：** `data/interest_profile.json` → `rag_dimensions` 字段

每个 dimension 有一个 weight，RAG 用这些做**多路召回**：

```json
{
  "rag_dimensions": [
    {"name": "财务系统", "query": "财务系统架构 ERP SAP 费控 核算 月结", "weight": 0.4},
    {"name": "AI产品", "query": "大模型 Agent RAG prompt工程 AI应用落地", "weight": 0.35}
  ]
}
```

**怎么调：**
- 编辑 `data/interest_profile.json`，修改 query 文本让它更精准
- 增加/删除维度
- 调整 weight 控制该维度在回顾中的占比
- 运行 `bash profile.sh gen` 重新生成画像（会覆盖手动修改！）

### 环节3：检索 & 评估

**怎么判断检索好坏：**
- 前3条是否直接相关你的查询？
- 是否有明显应该出现但没出现的段落？→ query 表达方式需要调整
- 是否有不相关的结果排在前面？→ 需要调整 chunk_size 或添加过滤

**测试方法：**
```bash
bash rag_tune.sh search <你知道文档里有的内容>
# 比如你的文档明确写了"灵知月结中台"，搜这个看看是否排在前3
```

### 环节4：重排序

当前使用简单的关键词匹配排序。如果要加向量检索（语义相似度），需要先将 chunk 导入 ChromaDB。

### 环节5：回顾输出

回顾邮件 = RAG检索结果 + 网络发现。当前实现在 `src/skills/daily_digest_skill.py`。

---

## 日常操作

### 飞书文档更新后
```bash
bash feishu_sync.sh          # 同步一次
# 或设置 cron 自动同步:
# 0 */3 * * * cd /path/to/knowledge-agent && bash feishu_sync.sh >> logs/feishu_sync.log 2>&1
```

### 发送每日回顾
```bash
bash daily_digest.sh         # 先同步飞书，再发送邮件
```

### 新增监控文档
编辑 `config/feishu_sources.yaml`，添加 URL：
```yaml
sources:
  - url: "https://my.feishu.cn/wiki/xxxxx"
  - url: "https://my.feishu.cn/base/xxxxx?table=xxx"
```

---

## 文件索引

| 文件 | 作用 |
|------|------|
| `rag_tune.sh` | RAG 调优入口脚本 |
| `src/skills/rag_tuner.py` | 分块、检索、对比逻辑 |
| `src/skills/daily_digest_skill.py` | 每日回顾邮件生成 |
| `src/skills/feishu_skill.py` | 飞书同步 + 自动更新检测 |
| `src/knowledge/sqlite_store.py` | 知识库存储（含 raw_content 原文列） |
| `src/knowledge/chroma_store.py` | ChromaDB 向量库 |
| `config/feishu_sources.yaml` | 飞书文档监控列表 |
| `config/content_sources.yaml` | 网络内容源（RSS/网页） |
| `data/interest_profile.json` | 用户兴趣画像（手动编辑或 `bash profile.sh gen` 生成） |
| `prompts/keyword_profile_prompt.txt` | 画像生成 prompt |

---

## 常见问题

**Q: 回顾内容不是我文档里的？**
A: 检查 `config/feishu_sources.yaml` 是否配置了正确的 URL，运行 `bash feishu_sync.sh` 确保同步。

**Q: 分块在句子中间切断？**
A: 增大 chunk_size，或改用 L2 按段落策略。

**Q: 一个 chunk 包含多个不相关主题？**
A: 减小 chunk_size，或在飞书文档里加空行分隔。

**Q: 检索返回很多不相关结果？**
A: 优化 `data/interest_profile.json` 中 rag_dimensions 的 query 文本，用更精确的关键词。

**Q: 邮件太短/太长？**
A: 调整 `daily_digest_skill.py` 中的 `MAX_CHARS_PER_DOC`（默认5000）。
