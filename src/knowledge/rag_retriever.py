"""
RAG 检索器 — 语义搜索知识库

组合 Embedding 和 Chroma，提供统一的检索入口。
支持纯语义检索（Chroma）和混合检索（关键词 + 语义融合）。
"""
import logging

logger = logging.getLogger(__name__)


def search(
    query: str,
    top_k: int = 10,
    use_keyword_fallback: bool = True,
) -> list[dict]:
    """
    语义搜索知识库。

    流程：query → Embedding → Chroma 向量检索 → 返回结果

    Args:
        query: 搜索查询文本
        top_k: 返回结果数量
        use_keyword_fallback: 向量检索失败时是否回退到 SQLite 关键词搜索

    Returns:
        [
            {
                "title": "...",
                "summary": "...",
                "category": "...",
                "tags": [...],
                "source_type": "...",
                "source_path": "...",
                "similarity_score": 0.95,
            },
            ...
        ]
    """
    # ── 向量检索 ──
    try:
        from skills.embedding_skill import embed_text
        from knowledge.chroma_store import search_similar

        query_embedding = embed_text(query)
        if query_embedding:
            results = search_similar(query_embedding, n_results=top_k)
            if results:
                logger.info(f"RAG 语义检索成功，返回 {len(results)} 条")
                return results
    except Exception as e:
        logger.warning(f"向量检索失败: {e}")

    # ── 关键词回退 ──
    if use_keyword_fallback:
        try:
            from skills.sqlite_skill import search_knowledge
            results = search_knowledge(query, limit=top_k)
            # 给关键词结果也加上 score 字段
            for r in results:
                r["similarity_score"] = None
                r["search_method"] = "keyword"
            if results:
                logger.info(f"关键词回退成功，返回 {len(results)} 条")
            return results
        except Exception as e:
            logger.warning(f"关键词回退也失败: {e}")

    return []


def hybrid_search(
    query: str,
    top_k: int = 10,
    vector_weight: float = 0.7,
) -> list[dict]:
    """
    混合检索：向量相似度 × 权重 + 关键词匹配补充

    Args:
        query: 搜索查询
        top_k: 返回数量
        vector_weight: 向量结果的权重 (0-1)，越大越偏向语义

    Returns:
        融合后的结果列表
    """
    # 向量检索
    vector_results = {}
    try:
        from skills.embedding_skill import embed_text
        from knowledge.chroma_store import search_similar
        q_emb = embed_text(query)
        if q_emb:
            for item in search_similar(q_emb, n_results=top_k * 2):
                vid = item.get("id", "")
                item["_vector_score"] = item.pop("similarity_score", 0)
                vector_results[vid] = item
    except Exception:
        pass

    # 关键词检索
    keyword_results = {}
    try:
        from skills.sqlite_skill import search_knowledge
        for item in search_knowledge(query, limit=top_k * 2):
            kid = item.get("id", "")
            item["_keyword_score"] = 1.0  # 关键词匹配默认满分
            keyword_results[kid] = item
    except Exception:
        pass

    # 融合：vector_weight * vector_score + (1-vector_weight) * keyword_score
    fused = {}
    all_ids = set(vector_results.keys()) | set(keyword_results.keys())
    for rid in all_ids:
        v = vector_results.get(rid, {})
        k = keyword_results.get(rid, {})
        merged = v or k  # 取任一作为基础
        v_score = v.get("_vector_score", 0) or 0
        k_score = k.get("_keyword_score", 0) or 0
        merged["similarity_score"] = round(
            vector_weight * v_score + (1 - vector_weight) * k_score, 4
        )
        merged["search_method"] = "hybrid"
        fused[rid] = merged

    # 按分数排序取 top_k
    sorted_items = sorted(
        fused.values(),
        key=lambda x: x.get("similarity_score", 0),
        reverse=True,
    )
    return sorted_items[:top_k]
