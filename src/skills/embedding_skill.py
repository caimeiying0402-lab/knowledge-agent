"""
Embedding Skill — 文本向量化

优先使用 DeepSeek Embedding API（已有 Key，零额外配置），
失败则退回到本地 BGE 模型（需 pip install sentence-transformers）。

两种方案都不可用时静默跳过，不阻塞主流程。
"""
import logging

logger = logging.getLogger(__name__)

# 缓存已选择的方案
_embedding_method = None  # "deepseek" | "bge_local" | None
_embed_model = None  # SentenceTransformer 实例（BGE 方案时）


def embed_text(text: str) -> list[float] | None:
    """
    对文本生成 Embedding 向量。

    Args:
        text: 待向量化的文本

    Returns:
        float 列表（向量），失败返回 None
    """
    global _embedding_method

    if not text or not text.strip():
        return None

    # 截断过长文本（大部分 embedding 模型有 token 限制）
    text = text[:8000]

    # ── 方案 1：DeepSeek Embedding API ──
    if _embedding_method is None or _embedding_method == "deepseek":
        result = _embed_deepseek(text)
        if result is not None:
            _embedding_method = "deepseek"
            return result

    # ── 方案 2：本地 BGE 模型 ──
    if _embedding_method is None or _embedding_method == "bge_local":
        result = _embed_bge_local(text)
        if result is not None:
            _embedding_method = "bge_local"
            return result

    logger.warning("所有 Embedding 方案均不可用，向量化跳过")
    _embedding_method = "unavailable"
    return None


def embed_record(record: dict) -> list[float] | None:
    """
    对知识记录生成 Embedding（拼接 title + summary + tags）。

    Args:
        record: 知识记录 dict

    Returns:
        float 列表（向量），失败返回 None
    """
    text_parts = [
        record.get("title", ""),
        record.get("summary", ""),
        " ".join(record.get("tags", [])),
    ]
    combined = " ".join(filter(None, text_parts))
    return embed_text(combined)


# ── 内部实现 ──

def _embed_deepseek(text: str) -> list[float] | None:
    """DeepSeek Embedding API"""
    try:
        from models.deepseek_client import client
        response = client.embeddings.create(
            model="deepseek-chat",  # DeepSeek chat model 也支持 embedding
            input=text,
        )
        embedding = response.data[0].embedding
        logger.debug(f"DeepSeek Embedding 成功，维度={len(embedding)}")
        return embedding
    except Exception as e:
        logger.debug(f"DeepSeek Embedding 失败: {e}")
        return None


def _embed_bge_local(text: str) -> list[float] | None:
    """本地 BGE 模型"""
    global _embed_model
    try:
        if _embed_model is None:
            from sentence_transformers import SentenceTransformer
            _embed_model = SentenceTransformer("BAAI/bge-small-zh-v1.5")
            logger.info("BGE 本地 Embedding 模型已加载")
        vec = _embed_model.encode(text)
        return vec.tolist()
    except ImportError:
        logger.debug("sentence-transformers 未安装，跳过本地 Embedding")
        return None
    except Exception as e:
        logger.debug(f"BGE Embedding 失败: {e}")
        return None
