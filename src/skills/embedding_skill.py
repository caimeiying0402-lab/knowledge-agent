"""
Embedding Skill v4 — 文本向量化（macOS x86_64 兼容版）

方案优先级：
1. 阿里云百炼 text-embedding-v4（中文优化，OpenAI 兼容接口，有免费额度）
2. ChromaDB 默认 ONNX Embedding（all-MiniLM-L6-v2，零额外依赖，开箱即用）

注意：DeepSeek 不支持 Embedding API，BGE 本地模型需要 PyTorch >= 2.4
      而 macOS x86_64 最高只支持 PyTorch 2.2.2，因此不再使用这两个方案。

每个方案只尝试一次，失败后缓存"不可用"状态，后续调用直接跳过。
"""
import logging

logger = logging.getLogger(__name__)

# 缓存已选择的方案
_embedding_method = None  # "dashscope" | "chroma_default" | "unavailable"
_chroma_ef = None  # ChromaDB DefaultEmbeddingFunction 实例


def embed_text(text: str) -> list[float] | None:
    """将文本转为向量。优先百炼 API，备选 ChromaDB ONNX 本地模型。"""
    if not text or not text.strip():
        return None
    global _embedding_method
    if _embedding_method == "unavailable":
        return None
    text = text[:8000]

    # ── 方案 1：阿里云百炼 Embedding API ──
    if _embedding_method is None:
        result = _embed_dashscope(text)
        if result is not None:
            _embedding_method = "dashscope"
            return result
        _embedding_method = "dashscope_unavailable"
        logger.info("阿里云百炼 Embedding 不可用，尝试 ChromaDB 本地 ONNX...")

    # ── 方案 2：ChromaDB 默认 ONNX Embedding ──
    if _embedding_method in (None, "dashscope_unavailable"):
        result = _embed_chroma_default(text)
        if result is not None:
            _embedding_method = "chroma_default"
            return result
        _embedding_method = "unavailable"
        logger.warning("所有 Embedding 方案均不可用，向量化跳过（已缓存，不再重试）")

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


def _embed_dashscope(text: str) -> list[float] | None:
    """阿里云百炼 text-embedding-v4，OpenAI 兼容接口"""
    try:
        import os
        from openai import OpenAI
        from dotenv import load_dotenv
        from pathlib import Path

        # 加载 .env
        env_path = Path(__file__).parent.parent.parent / "config" / ".env"
        load_dotenv(env_path)

        api_key = os.getenv("ALIYUN_API_KEY", "")
        if not api_key:
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
        logger.info(f"百炼 Embedding 成功，维度={len(embedding)}")
        return embedding
    except Exception as e:
        logger.debug(f"百炼 Embedding 不可用: {e}")
        return None


def _embed_chroma_default(text: str) -> list[float] | None:
    """ChromaDB 自带的 ONNX Embedding（all-MiniLM-L6-v2），无需 PyTorch"""
    global _chroma_ef
    try:
        if _chroma_ef is None:
            from chromadb.utils import embedding_functions
            _chroma_ef = embedding_functions.DefaultEmbeddingFunction()
            logger.info("ChromaDB ONNX Embedding 已加载 (all-MiniLM-L6-v2)")
        result = _chroma_ef([text])
        if result and len(result) > 0:
            embedding = result[0].tolist()
            logger.debug(f"ChromaDB ONNX Embedding 成功，维度={len(embedding)}")
            return embedding
        return None
    except ImportError:
        logger.debug("chromadb 未安装，跳过 ONNX Embedding")
        return None
    except Exception as e:
        logger.debug(f"ChromaDB ONNX Embedding 失败: {e}")
        return None


def get_embedding_method() -> str:
    """返回当前使用的 embedding 方案名称"""
    return _embedding_method or "not_initialized"
