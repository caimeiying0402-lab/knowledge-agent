"""
RAG 调优工具 — 查看分块效果、测试检索、对比参数

核心理念：每个环节对人类透明，参数可调。
分块策略从简单到复杂递进：
  L1: 固定长度切分（最基础，先看效果）
  L2: 按空行/段落边界切分（尊重自然段落）
  L3: 按标题层级切分（尊重文档结构）
"""

import re
import json
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.parent
COLLECTION_NAME = "doc_chunks"


# ═══════════════════════════════════════════════════════════
# 分块策略 — 三种级别，人类可选择
# ═══════════════════════════════════════════════════════════

def chunk_fixed_size(text: str, size: int = 500, overlap: int = 100) -> list[dict]:
    """L1: 固定长度切分，overlap 衔接上下文"""
    chunks = []
    start = 0
    idx = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunk_text = text[start:end].strip()
        if chunk_text:
            chunks.append({
                "index": idx,
                "text": chunk_text,
                "char_start": start,
                "char_end": end,
                "strategy": f"fixed_{size}",
            })
            idx += 1
        start += (size - overlap)
    return chunks


def chunk_by_paragraphs(text: str, max_chunk_size: int = 800) -> list[dict]:
    """L2: 按空行分段落，合并短段落，不切长段落"""
    # 1. 按空行切分
    raw_blocks = re.split(r'\n\s*\n', text)

    # 2. 过滤纯空白/图片行
    blocks = []
    for b in raw_blocks:
        b = b.strip()
        if not b:
            continue
        if re.match(r'^[A-Za-z0-9_\-]+\.(?:heic|png|jpg|jpeg|gif|webp|bmp)\s*$', b, re.IGNORECASE):
            continue
        if re.match(r'^[A-Fa-f0-9]{8}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{12}\s*$', b):
            continue
        blocks.append(b)

    # 3. 合并短块，直到接近 max_chunk_size
    chunks = []
    buffer = []
    buffer_len = 0

    for block in blocks:
        block_len = len(block)

        # 看起来像标题的短行（<60字，无句号结尾）→ 尽量独立成 chunk
        looks_like_heading = (
            block_len < 60
            and "\n" not in block
            and not block.endswith(("。", "）", "）", ".", "!", "！", "?", "？"))
        )

        if looks_like_heading:
            # 先吐出 buffer 中的内容
            if buffer:
                chunks.append(_make_chunk(buffer, len(chunks), "paragraph"))
                buffer = []
                buffer_len = 0
            # 标题作为独立 chunk
            chunks.append(_make_chunk([block], len(chunks), "heading"))
            continue

        # 如果当前块加入会超出 max_chunk_size，先吐出 buffer
        if buffer_len + block_len > max_chunk_size and buffer:
            chunks.append(_make_chunk(buffer, len(chunks), "paragraph"))
            buffer = []
            buffer_len = 0

        buffer.append(block)
        buffer_len += block_len

    if buffer:
        chunks.append(_make_chunk(buffer, len(chunks), "paragraph"))

    return chunks


def _make_chunk(lines: list[str], idx: int, strategy: str) -> dict:
    text = "\n\n".join(lines)
    return {
        "index": idx,
        "text": text,
        "line_count": len(lines),
        "strategy": strategy,
    }


# ═══════════════════════════════════════════════════════════
# 文档加载
# ═══════════════════════════════════════════════════════════

def _load_feishu_documents() -> list[dict]:
    """加载配置的飞书文档的原文"""
    import yaml
    from knowledge.sqlite_store import _get_conn

    config_path = BASE_DIR / "config" / "feishu_sources.yaml"
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return []

    sources = config.get("sources", [])
    if not sources:
        return []

    from skills.feishu_skill import _extract_token_from_url
    conn = _get_conn()
    docs = []

    for src in sources:
        url = src.get("url", "").strip()
        if not url:
            continue
        info = _extract_token_from_url(url)
        token = info.get("token", "")
        if not token:
            continue

        rows = conn.execute(
            """SELECT id, title, raw_content, full_content, category, source_type
               FROM knowledge_items
               WHERE source_path LIKE ? AND raw_content IS NOT NULL AND raw_content != ''
               ORDER BY created_at DESC""",
            (f"%{token}%",),
        ).fetchall()

        for row in rows:
            raw = row["raw_content"] or row["full_content"] or ""
            if raw:
                docs.append({
                    "id": row["id"],
                    "title": row["title"] or "",
                    "raw_content": raw,
                    "category": row["category"] or "",
                    "source_type": row["source_type"] or "",
                })

    return docs


# ═══════════════════════════════════════════════════════════
# 对外接口 — rag_tune.sh 调用
# ═══════════════════════════════════════════════════════════

def list_documents():
    """列出所有可检索的文档"""
    docs = _load_feishu_documents()
    if not docs:
        print("没有找到飞书文档。请先配置 config/feishu_sources.yaml 并运行同步。")
        return

    print(f"共 {len(docs)} 篇文档:\n")
    wiki = [d for d in docs if d["source_type"] in ("feishu_wiki", "feishu_docx", "feishu_doc")]
    bitable = [d for d in docs if d["source_type"] == "feishu_bitable"]

    for d in wiki:
        raw = d["raw_content"]
        paras = len(re.split(r'\n\s*\n', raw))
        print(f"  📄 {d['title'][:60]}")
        print(f"     {len(raw)}字 | ~{paras}个自然段 | {d['category']}")
        print()

    if bitable:
        print(f"  📊 bitable 条目: {len(bitable)}条")
        for d in bitable[:5]:
            print(f"     ▸ {d['title'][:60]} ({len(d['raw_content'])}字)")
        if len(bitable) > 5:
            print(f"     ... 还有 {len(bitable) - 5} 条")
        print()


def show_chunks(name_filter: str = ""):
    """
    展示文档的分块结果。
    三级策略并排展示，让人类对比哪种更符合预期。
    """
    docs = _load_feishu_documents()
    if not docs:
        print("没有找到文档")
        return

    # 过滤
    if name_filter:
        docs = [d for d in docs if name_filter in d["title"]]
    if not docs:
        print(f"未找到包含 '{name_filter}' 的文档")
        return

    doc = docs[0]  # 取第一个匹配的
    text = doc["raw_content"]
    title = doc["title"]

    print(f"📄 {title} （{len(text)}字）\n")
    print("=" * 70)

    # 展示三种分块策略的结果
    strategies = [
        ("L1 固定500字 (overlap=100)", chunk_fixed_size(text, 500, 100)),
        ("L2 按段落边界 (max=800字)", chunk_by_paragraphs(text, 800)),
        ("L3 按段落边界 (max=400字)", chunk_by_paragraphs(text, 400)),
    ]

    for name, chunks in strategies:
        print(f"\n{'─' * 70}")
        print(f"🔧 {name}")
        print(f"   产生 {len(chunks)} 个 chunk")
        print(f"{'─' * 70}")

        for c in chunks[:8]:  # 只展示前8个，太多看不清
            idx = c["index"]
            strategy = c.get("strategy", "?")
            text_preview = c["text"][:200].replace("\n", "\\n")
            print(f"\n  [{idx}] ({strategy}, {len(c['text'])}字)")
            # 展示实际文本
            for line in c["text"].split("\n")[:6]:
                print(f"     │ {line.rstrip()[:100]}")

        if len(chunks) > 8:
            print(f"\n  ... 还有 {len(chunks) - 8} 个 chunk，用更小的 max_chunk_size 可看到更多")
        print()

    print("=" * 70)
    print("\n💡 调优建议:")
    print("   - 如果 chunk 经常在句子中间断开 → 增大 chunk_size")
    print("   - 如果 chunk 包含多个不相关主题 → 减小 chunk_size 或使用 L2/L3")
    print("   - 如果标题和内容被拆到不同 chunk → 使用 L2 策略")
    print("   - 选定策略后，用 'bash rag_tune.sh search <查询>' 测试检索效果")


def test_search(query: str = ""):
    """测试 RAG 检索：输入查询，看返回哪些 chunk"""
    if not query:
        print("请提供查询文本，例如: bash rag_tune.sh search 财务系统架构")
        return

    docs = _load_feishu_documents()
    if not docs:
        print("没有找到文档")
        return

    # 用 L2 策略对所有文档分块
    all_chunks = []
    for doc in docs:
        if doc["source_type"] == "feishu_bitable":
            # bitable 条目短，每条作为一个 chunk
            chunks = [{
                "index": 0,
                "text": doc["raw_content"],
                "strategy": "bitable_entry",
                "doc_title": doc["title"],
            }]
        else:
            chunks = chunk_by_paragraphs(doc["raw_content"], max_chunk_size=800)
            for c in chunks:
                c["doc_title"] = doc["title"]
        all_chunks.extend(chunks)

    print(f"🔍 查询: \"{query}\"\n")
    print(f"📊 共 {len(all_chunks)} 个 chunk 待检索\n")

    # 简易 BM25 风格的关键词匹配 + 向量检索（如果有 ChromaDB）
    results = _keyword_retrieve(query, all_chunks, top_k=8)

    if not results:
        print("没有找到相关结果")
        return

    print("=" * 70)
    print("检索结果（关键词匹配 + 排序）")
    print("=" * 70)

    for i, (chunk, score) in enumerate(results):
        doc_title = chunk.get("doc_title", "?")
        text = chunk["text"]
        strategy = chunk.get("strategy", "?")

        print(f"\n── #{i+1} [相关度: {score:.2f}] ──")
        print(f"   来源: {doc_title[:60]}")
        print(f"   策略: {strategy} | {len(text)}字")
        print(f"   {'─' * 50}")

        # 高亮匹配的关键词
        for line in text.split("\n")[:8]:
            highlighted = _highlight_keywords(line, query)
            print(f"   │ {highlighted[:120]}")

        if len(text.split("\n")) > 8:
            print(f"   │ ... (共{len(text.split(chr(10)))}行)")

    print(f"\n{'=' * 70}")
    print("\n💡 评估检索质量:")
    print("   - 前3条是否直接回答了你的查询？")
    print("   - 是否有明显应该出现但没出现的段落？（→ 调整 query 表达方式）")
    print("   - 是否有不相关的结果排在前面？（→ 调整检索权重或 chunk 大小）")
    print("   - 用 'bash rag_tune.sh compare <查询>' 对比不同 chunk_size 的检索差异")


def compare_chunk_sizes(query: str = ""):
    """对比不同 chunk_size 的检索效果差异"""
    if not query:
        print("请提供查询文本")
        return

    docs = _load_feishu_documents()
    if not docs:
        print("没有找到文档")
        return

    # 只对 wiki 文档测试（bitable 太短不做对比）
    wiki_docs = [d for d in docs if d["source_type"] != "feishu_bitable"]
    if not wiki_docs:
        print("没有长文档可对比")
        return

    configs = [
        ("固定 300字", lambda t: chunk_fixed_size(t, 300, 50)),
        ("固定 500字", lambda t: chunk_fixed_size(t, 500, 100)),
        ("段落 max=400", lambda t: chunk_by_paragraphs(t, 400)),
        ("段落 max=800", lambda t: chunk_by_paragraphs(t, 800)),
    ]

    print(f"🔍 查询: \"{query}\"\n")
    print("对比不同分块策略的 TOP-3 检索结果:\n")

    for strategy_name, chunk_fn in configs:
        all_chunks = []
        for doc in wiki_docs:
            chunks = chunk_fn(doc["raw_content"])
            for c in chunks:
                c["doc_title"] = doc["title"]
            all_chunks.extend(chunks)

        results = _keyword_retrieve(query, all_chunks, top_k=3)

        print(f"{'─' * 70}")
        print(f"🔧 {strategy_name} → {len(all_chunks)} chunks")
        for i, (chunk, score) in enumerate(results):
            text_preview = chunk["text"][:120].replace("\n", " ")
            print(f"   #{i+1} [{score:.2f}] {chunk.get('doc_title', '')[:30]}")
            print(f"        \"{text_preview}...\"")
        print()


def show_profile_context():
    """展示当前用于 RAG 检索的用户画像"""
    from skills.keyword_profile_skill import load_profile
    profile = load_profile()

    print("当前用户兴趣画像\n")
    print(f"生成时间: {profile.get('generated_at', 'unknown')}")
    print(f"人工审阅: {profile.get('last_curated_at') or '未审阅'}")
    print()

    summary = profile.get("summary", "")
    if summary:
        print(f"📝 画像摘要: {summary}\n")

    keywords = profile.get("keywords", [])
    if keywords:
        print("🔑 兴趣关键词:")
        for kw in keywords[:10]:
            w = kw.get("curated_weight") or kw.get("weight", 0)
            curated = "✏️ 人工" if kw.get("curated") else "🤖 自动"
            print(f"   [{w:.0%}] {kw['term']} ({kw.get('category', '')}) {curated}")
        print()

    rag_dims = profile.get("rag_dimensions", [])
    if rag_dims:
        print("📐 RAG 检索维度（review 会用这些做多路召回）:")
        for d in rag_dims:
            print(f"   [{d['weight']:.0%}] {d['name']}")
            print(f"        query: {d['query'][:100]}")
        print()

    search_queries = profile.get("search_queries", [])
    if search_queries:
        print("🔍 搜索查询（发现新知识用）:")
        for q in search_queries[:5]:
            print(f"   • {q}")
        print()

    print("💡 调优方式:")
    print("   1. 编辑 data/interest_profile.json 修改关键词和权重")
    print("   2. 运行 bash profile.sh gen 重新生成画像")
    print("   3. RAG 检索维度决定了 review 会召回什么类型的段落")


# ═══════════════════════════════════════════════════════════
# 简易检索 — 不依赖 ChromaDB，关键词直接匹配
# ═══════════════════════════════════════════════════════════

def _keyword_retrieve(query: str, chunks: list[dict], top_k: int = 8) -> list[tuple]:
    """关键词匹配 + 简单排序。用于快速测试，不依赖向量库。"""
    # 分词（中英文混合）
    query_terms = _tokenize(query)
    if not query_terms:
        return []

    scored = []
    for chunk in chunks:
        text = chunk["text"]
        score = 0.0
        for term in query_terms:
            count = text.count(term)
            if count > 0:
                # TF 因子：关键词出现次数
                tf = count / max(len(text), 1)
                # 标题中出现加分
                doc_title = chunk.get("doc_title", "")
                if term in doc_title:
                    tf *= 2.0
                # heading chunk 加分（标题通常是关键信息）
                if chunk.get("strategy") == "heading":
                    tf *= 1.5
                score += tf
        # 长度惩罚：过长 chunk 降权
        score *= min(1.0, 500 / max(len(text), 1))
        if score > 0:
            scored.append((chunk, score))

    scored.sort(key=lambda x: -x[1])
    return scored[:top_k]


def _tokenize(text: str) -> list[str]:
    """中英文混合分词"""
    tokens = []
    # 中文：按常见分隔符拆
    chinese_parts = re.split(r'[，。！？、\s]+', text)
    for part in chinese_parts:
        part = part.strip()
        if len(part) >= 2:
            tokens.append(part)
            # 二元组
            if len(part) >= 4:
                for i in range(len(part) - 1):
                    bigram = part[i:i+2]
                    if bigram not in tokens:
                        tokens.append(bigram)
        elif len(part) == 1 and part.isalpha():
            tokens.append(part)
    # 英文词
    english_words = re.findall(r'[a-zA-Z]{2,}', text)
    tokens.extend(w.lower() for w in english_words)
    return list(set(tokens))


def _highlight_keywords(line: str, query: str) -> str:
    """给匹配的关键词加上标记"""
    terms = _tokenize(query)
    result = line
    for term in sorted(terms, key=len, reverse=True):
        if term in result:
            result = result.replace(term, f"【{term}】")
    return result
