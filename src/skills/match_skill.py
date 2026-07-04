"""岗位匹配评分引擎 — 简历JSON × JD文本 → 0-100分 + 匹配理由"""
import json
import logging
from pathlib import Path
from models.deepseek_client import chat

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent

DEFAULT_RESULT = {
    "score": 0,
    "breakdown": {"domain": 0, "skill": 0, "experience": 0, "industry": 0, "highlights": 0},
    "match_points": [],
    "gap_points": [],
    "overall_assessment": "匹配失败",
    "suggestion": "不建议"
}


PERSONAL_INFO_PATH = Path("/Users/caimeiying/AI-Agent-Lab/skills/personal_info.md")


def load_personal_info() -> str:
    """加载个人资料（唯一数据源）"""
    if PERSONAL_INFO_PATH.exists():
        return PERSONAL_INFO_PATH.read_text(encoding="utf-8")
    logger.warning(f"personal_info.md 不存在: {PERSONAL_INFO_PATH}")
    return ""


def match(jd_text: str, personal_info: str = "") -> dict:
    """
    对岗位JD进行匹配评分。

    Args:
        jd_text: 岗位JD文本
        personal_info: 个人资料 Markdown（可选，默认自动加载）

    Returns:
        {"score": int, "breakdown": {...}, "match_points": [...],
         "gap_points": [...], "overall_assessment": str, "suggestion": str}
    """
    if not personal_info:
        personal_info = load_personal_info()
    if not personal_info:
        return DEFAULT_RESULT

    prompt_path = BASE_DIR / "prompts" / "job_match_prompt.txt"
    with open(prompt_path, "r", encoding="utf-8") as f:
        system_prompt = f.read()

    user_message = f"【候选人详细资料】\n{personal_info}\n\n【目标岗位JD】\n{jd_text}"

    # 3. 调用 DeepSeek
    response = chat(system_prompt, user_message)
    logger.debug(f"DeepSeek raw response:\n{response[:500]}")

    # 4. 解析 JSON
    try:
        cleaned = response.strip().strip("```json").strip("```").strip()
        result = json.loads(cleaned)
        return _validate_result(result)
    except json.JSONDecodeError as e:
        logger.warning(f"JSON 解析失败: {e}")
        last_brace = response.rfind("}")
        if last_brace > 0:
            try:
                result = json.loads(response[:last_brace + 1])
                return _validate_result(result)
            except json.JSONDecodeError:
                pass
        return DEFAULT_RESULT


def _validate_result(result: dict) -> dict:
    """验证并补齐返回字段"""
    validated = {}
    validated["score"] = max(0, min(100, int(result.get("score", 0))))
    breakdown = result.get("breakdown", {})
    validated["breakdown"] = {
        "domain": max(0, min(30, int(breakdown.get("domain", 0)))),
        "skill": max(0, min(25, int(breakdown.get("skill", 0)))),
        "experience": max(0, min(20, int(breakdown.get("experience", 0)))),
        "industry": max(0, min(15, int(breakdown.get("industry", 0)))),
        "highlights": max(0, min(10, int(breakdown.get("highlights", 0)))),
    }
    validated["match_points"] = (result.get("match_points", []) or [])[:6]
    validated["gap_points"] = (result.get("gap_points", []) or [])[:4]
    validated["overall_assessment"] = (result.get("overall_assessment", "") or "")
    validated["suggestion"] = (result.get("suggestion", "不建议") or "不建议")
    return validated
