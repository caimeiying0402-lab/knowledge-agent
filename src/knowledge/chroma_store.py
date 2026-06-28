"""
Chroma 向量库 v2 — 知识条目 Embedding 存储与语义检索

改进：
- 当外部提供 embedding 时直接使用
- 当未提供 embedding 时，使用 ChromaDB 内置的 DefaultEmbeddingFunction 自动生成
- 路径备用逻辑：优先 data/chroma_db/，不可写时回退 ~/.cache/knowledge-agent/chroma_db/
"""
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

COLLECTION_NAME = "knowledge_items"

# 持久化路径（优先项目目录，回退到用户缓存目录）
_CHROMA_PATH_PRIMARY = Path(__file__).parent.parent.parent / "data" / "chroma_db"
_CHROMA_PATH_FALLBACK = Path.home() / ".cache" / "knowledge-agent" / "chroma_db"

_client = None
_collection = None


def _get_chroma_path() -> Path:
    """获取可写的 ChromaDB 路径"""
    # 尝试主路径
    try:
        _CHROMA_PATH_PRIMARY.mkdir(parents=True, exist_ok=True)
        test_file = _CHROMA_PATH_PRIMARY / ".write_test"
        test_file.write_text("test")
        test_file.unlink()
        return _CHROMA_PATH_PRIMARY
    except (PermissionError, OSError):
        pass

    # 回退到 ~/.cache
    try:
        _CHROMA_PATH_FALLBACK.mkdir(parents=True, exist_ok=True)
        logger.info(f"ChromaDB 主路径不可写，回退到: {_CHROMA_PATH_FALLBACK}")
        return _CHROMA_PATH_FALLBACK
    except (PermissionError, OSError) as e:
        logger.error(f"ChromaDB 所有路径均不可写: {e}")
        return None


def _get_collection():
    """获取或创建 Chroma collection（懒加载 + 单例）"""
    global _client, _collection
    if _collection is not None:
        return _collection

    try:
        import chromadb
        from chromadb.config import Settings
        from chromadb.utils import embedding_functions

        chroma_path = _get_chroma_path()
        if chroma_path is None:
            return None

        _client = chromadb.PersistentClient(
            path=str(chroma_path),
            settings=Settings(anonymized_telemetry=False),
        )

        # 使用 ChromaDB 默认的 ONNX embedding function
        # 这样即使不手动提供 embedding，add 时也能自动向量化
        default_ef = embedding_functions.DefaultEmbeddingFunction()

        _collection = _client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
            embedding_function=default_ef,
        )
        logger.info(f"ChromaDB 已就绪: {chroma_path}")
        return _collection
    except ImportError:
        logger.warning(
            "chromadb 未安装，向量检索不可用。安装: pip install chromadb"
        )
        return None
    except Exception as e:
        logger.warning(f"ChromaDB 初始化失败: {e}")
        return None


def add_to_chroma(record: dict, embedding: list[float] | None = None) -> bool:
    """
    将一条知识记录存入 Chroma。

    如果提供了 embedding（来自百炼 API 等），直接使用；
    如果没有，ChromaDB 会自动使用内置 ONNX 模型生成向量。

    Args:
        record: 知识记录 dict（需包含 id, title, summary, category, tags 等）
        embedding: 可选的外部 embedding 向量。为 None 时由 ChromaDB 自动生成。

    Returns:
        是否成功
    """
    collection = _get_collection()
    if collection is None:
        return False

    try:
        record_id = record.get("id", "")
        if not record_id:
            return False

        # 构建 metadata（只存轻量字段用于过滤和返回）
        metadata = {
            "title": record.get("title", ""),
            "summary": record.get("summary", "")[:500],  # 限制长度
            "category": record.get("category", ""),
            "tags": json.dumps(record.get("tags", []), ensure_ascii=False),
            "source_type": record.get("source_type", ""),
            "source_path": record.get("source_path", ""),
            "created_at": record.get("created_at", 0),
        }

        # 构建 document 文本（用于自动 embedding 和关键词检索）
        text_parts = [
            record.get("title", ""),
            record.get("summary", ""),
            " ".join(record.get("tags", [])),
        ]
        document = " ".join(filter(None, text_parts))

        # Upsert: 如果 ID 已存在则更新
        if embedding is not None:
            # 外部提供了 embedding（如百炼 API），直接使用
            collection.upsert(
                ids=[record_id],
                embeddings=[embedding],
                documents=[document],
                metadatas=[metadata],
            )
            logger.debug(f"Chroma 写入成功（外部 embedding，维度={len(embedding)}）: {record_id[:8]}")
        else:
            # 没有外部 embedding，让 ChromaDB 用内置 ONNX 模型自动生成
            collection.upsert(
                ids=[record_id],
                documents=[document],
                metadatas=[metadata],
            )
            logger.debug(f"Chroma 写入成功（自动 embedding）: {record_id[:8]}")
        return True
    except Exception as e:
        logger.warning(f"Chroma 写入失败: {e}")
        return False


def search_similar(
    query_embedding: list[float] | None = None,
    query_text: str = "",
    n_results: int = 10,
) -> list[dict]:
    """
    语义相似检索。

    支持两种模式：
    1. 提供 query_embedding：直接用外部向量搜索
    2. 提供 query_text：由 ChromaDB 内置 ONNX 模型自动向量化后搜索

    Args:
        query_embedding: 查询向量（可选）
        query_text: 查询文本（可选，当 query_embedding 为 None 时使用）
        n_results: 返回数量

    Returns:
        [{"id": ..., "title": ..., "summary": ..., "score": ...}, ...]
    """
    collection = _get_collection()
    if collection is None:
        return []

    try:
        if query_embedding is not None:
            # 用外部 embedding 搜索
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
            )
        elif query_text:
            # 让 ChromaDB 自动 embedding 后搜索
            results = collection.query(
                query_texts=[query_text],
                n_results=n_results,
            )
        else:
            return []

        items = []
        if results.get("ids") and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                item = {"id": doc_id}
                if results.get("metadatas") and results["metadatas"][0]:
                    meta = results["metadatas"][0][i] or {}
                    item.update(meta)
                    # 反序列化 tags
                    if "tags" in item and isinstance(item["tags"], str):
                        try:
                            item["tags"] = json.loads(item["tags"])
                        except (json.JSONDecodeError, TypeError):
                            item["tags"] = []
                if results.get("distances") and results["distances"][0]:
                    # cosine 距离转相似度: 1 - distance (cosine distance ∈ [0,2])
                    dist = results["distances"][0][i]
                    item["similarity_score"] = round(1 - dist / 2, 4)
                if results.get("documents") and results["documents"][0]:
                    item["document"] = results["documents"][0][i]
                items.append(item)
        return items
    except Exception as e:
        logger.warning(f"Chroma 检索失败: {e}")
        return []


def delete_from_chroma(record_id: str) -> bool:
    """从向量库删除一条记录"""
    collection = _get_collection()
    if collection is None:
        return False
    try:
        collection.delete(ids=[record_id])
        return True
    except Exception as e:
        logger.warning(f"Chroma 删除失败: {e}")
        return False


def get_chroma_stats() -> dict:
    """获取向量库统计"""
    collection = _get_collection()
    if collection is None:
        return {"available": False}
    try:
        count = collection.count()
        return {"available": True, "total_vectors": count}
    except Exception:
        return {"available": True, "total_vectors": "unknown"}
