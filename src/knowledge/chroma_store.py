"""
Chroma 向量库 — 知识条目 Embedding 存储与语义检索

Vector DB path: data/chroma_db/
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

COLLECTION_NAME = "knowledge_items"

# 持久化路径
_CHROMA_PATH = Path(__file__).parent.parent.parent / "data" / "chroma_db"

_client = None
_collection = None


def _get_collection():
    """获取或创建 Chroma collection（懒加载 + 单例）"""
    global _client, _collection
    if _collection is not None:
        return _collection

    try:
        import chromadb
        from chromadb.config import Settings

        _CHROMA_PATH.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(
            path=str(_CHROMA_PATH),
            settings=Settings(anonymized_telemetry=False),
        )
        _collection = _client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"ChromaDB 已就绪: {_CHROMA_PATH}")
        return _collection
    except ImportError:
        logger.warning(
            "chromadb 未安装，向量检索不可用。安装: pip install chromadb"
        )
        return None
    except Exception as e:
        logger.warning(f"ChromaDB 初始化失败: {e}")
        return None


def add_to_chroma(record: dict, embedding: list[float]) -> bool:
    """
    将一条知识记录和它的 embedding 向量存入 Chroma。

    Args:
        record: 知识记录 dict（需包含 id, title, summary, category, tags 等）
        embedding: float 列表，向量表示

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

        # 构建 metadata（只存轻量字段用于返回）
        metadata = {
            "title": record.get("title", ""),
            "summary": record.get("summary", ""),
            "category": record.get("category", ""),
            "tags": json.dumps(record.get("tags", []), ensure_ascii=False),
            "source_type": record.get("source_type", ""),
            "source_path": record.get("source_path", ""),
            "created_at": record.get("created_at", 0),
        }

        # 构建 embedding 文本（title + summary + tags 拼接）
        text_parts = [
            record.get("title", ""),
            record.get("summary", ""),
            " ".join(record.get("tags", [])),
        ]
        document = " ".join(filter(None, text_parts))

        # Upsert: 如果 ID 已存在则更新
        collection.upsert(
            ids=[record_id],
            embeddings=[embedding],
            documents=[document],
            metadatas=[metadata],
        )
        logger.debug(f"Chroma 写入成功: {record_id[:8]}")
        return True
    except Exception as e:
        logger.warning(f"Chroma 写入失败: {e}")
        return False


def search_similar(
    query_embedding: list[float], n_results: int = 10
) -> list[dict]:
    """
    语义相似检索。

    Args:
        query_embedding: 查询向量
        n_results: 返回数量

    Returns:
        [{"id": ..., "title": ..., "summary": ..., "score": ...}, ...]
    """
    collection = _get_collection()
    if collection is None:
        return []

    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
        )

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
