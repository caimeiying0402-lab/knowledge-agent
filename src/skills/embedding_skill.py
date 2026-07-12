"""
Embedding Skill v5 — 文本向量化

方案优先级：
1. ChromaDB ONNX (all-MiniLM-L6-v2, 384维) — 免费/本地/零配置，主力方案
2. 阿里云百炼 text-embedding-v4 (1024维) — 中文优化，需有效 API key，可选升级

注意：DeepSeek 无 Embedding API；BGE 本地模型需 PyTorch >= 2.4，
macOS x86_64 最高仅 PyTorch 2.2.2，故不可用。
"""
import logging

logger = logging.getLogger(__name__)

_chroma_ef = None
_dashscope_available = None  # None=未探测, True=可用, False=不可用


def embed_text(text: str) -> list[float] | None:
    """将文本转为向量。优先 ChromaDB ONNX，备选百炼 API。"""
    if not text or not text.strip():
        return None
    text = text[:8000]

    # ── 方案 1：ChromaDB ONNX（主力，免费本地）──
    result = _embed_chroma_default(text)
    if result is not None:
        return result

    # ── 方案 2：阿里云百炼（可选升级）──
    result = _embed_dashscope(text)
    if result is not None:
        return result

    logger.warning("所有 Embedding 方案均不可用，向量化跳过")
    return None


def embed_record(record: dict) -> list[float] | None:
    """将知识记录转为向量（拼接 title + summary + tags）"""
    text_parts = [
        record.get("title", ""),
        record.get("summary", ""),
        " ".join(record.get("tags", [])),
    ]
    combined = " ".join(filter(None, text_parts))
    return embed_text(combined)


def _embed_chroma_default(text: str) -> list[float] | None:
    """ChromaDB 自带的 ONNX Embedding（all-MiniLM-L6-v2, 384维）"""
    global _chroma_ef
    try:
        if _chroma_ef is None:
            from chromadb.utils import embedding_functions
            _chroma_ef = embedding_functions.DefaultEmbeddingFunction()
            logger.info("ChromaDB ONNX Embedding 已加载 (all-MiniLM-L6-v2, 384维)")
        result = _chroma_ef([text])
        if result and len(result) > 0:
            embedding = result[0].tolist()
            return embedding
        return None
    except ImportError:
        logger.debug("chromadb 未安装，ONNX Embedding 不可用")
        return None
    except Exception as e:
        logger.debug(f"ChromaDB ONNX Embedding 失败: {e}")
        return None


def _embed_dashscope(text: str) -> list[float] | None:
    """阿里云百炼 text-embedding-v4, 1024维, OpenAI 兼容接口"""
    global _dashscope_available
    if _dashscope_available is False:
        return None

    try:
        import os
        from openai import OpenAI
        from dotenv import load_dotenv
        from pathlib import Path

        env_path = Path(__file__).parent.parent.parent / "config" / ".env"
        load_dotenv(env_path)

        api_key = os.getenv("ALIYUN_API_KEY", "")
        if not api_key:
            _dashscope_available = False
            logger.debug("ALIYUN_API_KEY 未配置，跳过百炼 Embedding")
            return None

        client = OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        response = client.embeddings.create(
            model="text-embedding-v4",
            input=text,
            dimensions=1024,
            encoding_format="float",
        )
        embedding = response.data[0].embedding
        _dashscope_available = True
        logger.info(f"百炼 Embedding 成功，维度={len(embedding)}")
        return embedding
    except Exception as e:
        _dashscope_available = False
        logger.debug(f"百炼 Embedding 不可用: {e}")
        return None


def get_embedding_method() -> str:
    """返回当前使用的 embedding 方案名称（用于诊断）"""
    if _chroma_ef is not None:
        return "chroma_onnx"
    if _dashscope_available:
        return "dashscope"
    return "unavailable"
