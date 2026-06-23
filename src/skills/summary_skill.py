"""DeepSeek 摘要引擎 — v2：支持平台上下文 + 结构化字段"""
import json
import logging
from pathlib import Path
from models.deepseek_client import chat

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent

# ── 平台中文标签映射 ──
PLATFORM_LABELS = {
    "xiaohongshu": "小红书",
    "douban": "豆瓣",
    "wechat_mp": "微信公众号",
    "zhihu": "知乎",
    "baike_baidu": "百度百科",
    "sspai": "少数派",
    "wikipedia": "Wikipedia",
    "generic": "通用网页",
    "text": "纯文本",
    "file": "文件上传",
}

DEFAULT_RESULT = {
    "date": "",
    "title": "解析失败",
    "summary": "",
    "highlights": [],
    "category": "其他",
    "tags": ["未分类"],
    "source_quality": "low",
    "actionable": False,
}


def summarize(content: str, platform: str = "text") -> dict:
    """
    对采集内容进行结构化摘要。

    Args:
        content: 待处理的内容正文
        platform: 内容来源平台标识（xiaohongshu/douban/wechat_mp/...）

    Returns:
        {
            "date": str,           # YYYY-MM-DD
            "title": str,          # 15字标题
            "summary": str,        # 120-200字摘要
            "highlights": [str],   # 3-5个关键亮点
            "category": str,       # 分类（19类之一）
            "tags": [str],         # 3-5个标签
            "source_quality": str, # high/medium/low
            "actionable": bool,    # 是否可行动
        }
    """
    # ── 1. 加载 prompt ──
    prompt_path = BASE_DIR / "prompts" / "summary_prompt.txt"
    with open(prompt_path, "r", encoding="utf-8") as f:
        system_prompt = f.read()

    # ── 2. 构建带平台上下文的用户消息 ──
    platform_label = PLATFORM_LABELS.get(platform, "未知来源")
    user_message = (
        f"【来源平台】{platform_label}\n"
        f"【内容正文】\n{content}"
    )

    # ── 3. 调用 DeepSeek ──
    response = chat(system_prompt, user_message)
    logger.debug(f"DeepSeek raw response:\n{response[:500]}")

    # ── 4. 解析 JSON ──
    try:
        response = response.strip().strip("```json").strip("```").strip()
        result = json.loads(response)

        # 验证并填充缺失字段
        validated = _validate_result(result, content)
        return validated

    except json.JSONDecodeError as e:
        logger.warning(f"JSON 解析失败: {e}, raw={response[:200]}")

        # 尝试修复常见问题：尾部多余字符
        # 找到最后一个 } 并截断
        last_brace = response.rfind("}")
        if last_brace > 0:
            try:
                result = json.loads(response[:last_brace + 1])
                validated = _validate_result(result, content)
                logger.info("JSON 尾部截断修复成功")
                return validated
            except json.JSONDecodeError:
                pass

        return {
            **DEFAULT_RESULT,
            "summary": response[:200],
            "title": "解析失败",
        }


def _validate_result(result: dict, content: str = "") -> dict:
    """验证并补齐返回字段"""
    validated = {}

    # title
    title = result.get("title", "")
    validated["title"] = str(title)[:50] if title else "无标题"

    # summary
    summary = result.get("summary", "")
    validated["summary"] = str(summary)[:500] if summary else content[:200]

    # highlights
    highlights = result.get("highlights", [])
    if isinstance(highlights, list):
        validated["highlights"] = [str(h)[:100] for h in highlights[:5]]
    else:
        validated["highlights"] = []

    # category
    category = result.get("category", "其他")
    validated["category"] = str(category) if category else "其他"

    # tags
    tags = result.get("tags", [])
    if isinstance(tags, list) and tags:
        validated["tags"] = [str(t)[:30] for t in tags[:5]]
    else:
        validated["tags"] = ["未分类"]

    # source_quality
    sq = result.get("source_quality", "medium")
    validated["source_quality"] = sq if sq in ("high", "medium", "low") else "medium"

    # actionable
    validated["actionable"] = bool(result.get("actionable", False))

    # date
    validated["date"] = result.get("date", "")

    return validated
