"""
多模态识别技能 — PaddleOCR 本地引擎
零成本、离线可用、中文识别效果好
"""

import os
import logging
from pathlib import Path

logger = logging.getLogger("multimodal_skill")

# 延迟加载，避免每次 import 都初始化
_ocr_engine = None


def _get_ocr():
    """单例模式：首次调用时初始化 PaddleOCR，之后复用"""
    global _ocr_engine
    if _ocr_engine is None:
        from paddleocr import PaddleOCR

        # 指定模型缓存目录到项目内，避免写 ~/.paddleocr 被沙箱拦截
        cache_dir = str(Path(__file__).parent.parent.parent / ".paddleocr_cache")
        os.environ.setdefault("PADDLE_PDX_CACHE_HOME", cache_dir)

        logger.info("正在初始化 PaddleOCR 本地引擎（首次需下载模型，约 100MB）...")
        _ocr_engine = PaddleOCR(
            lang="ch",
            use_angle_cls=False,
            show_log=False,
        )
        logger.info("PaddleOCR 引擎就绪")
    return _ocr_engine


def image_to_text(image_path: str) -> str:
    """
    使用 PaddleOCR 本地引擎识别图片中的文字
    返回：识别出的纯文本，换行分隔
    """
    try:
        ocr = _get_ocr()
        result = ocr.ocr(str(image_path))

        lines = []
        if result and result[0]:
            for line in result[0]:
                text = line[1][0]
                lines.append(text)

        return "\n".join(lines) if lines else "[OCR] 未识别到文字"

    except Exception as e:
        logger.error(f"PaddleOCR 识别失败: {e}")
        return f"[OCR 识别失败] {e}"


def warmup():
    """预先加载 PaddleOCR 模型，避免首次请求时在线程中初始化的延迟和潜在 GIL 死锁"""
    logger.info("预热 PaddleOCR 引擎……")
    _get_ocr()
    # 用一张小测试图片跑一次，确保所有组件完全加载
    logger.info("PaddleOCR 预热完成")
