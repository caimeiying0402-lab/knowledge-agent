"""职业目标提取 — 从 personal_info.md 提取结构化职业目标，hash 缓存到 SQLite"""
import hashlib
import json
import logging
import time
from pathlib import Path

from models.deepseek_client import chat

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent
PERSONAL_INFO_PATH = Path("/Users/caimeiying/AI-Agent-Lab/skills/personal_info.md")

DEFAULT_GOALS = {
    "role": "产品经理",
    "domains": ["AI", "企业服务"],
    "skills_to_build": [],
    "target_industries": ["互联网"],
    "target_companies": [],
    "career_stage": "在职",
    "summary": "B端产品经理，关注AI方向",
}


def _hash_source(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def extract_career_goals(force_refresh: bool = False) -> dict:
    """提取职业目标，优先从缓存读取。force_refresh=True 强制重新提取。"""
    from knowledge.sqlite_store import get_career_goals, upsert_career_goals

    # 读取源文件
    try:
        with open(PERSONAL_INFO_PATH, "r", encoding="utf-8") as f:
            source_text = f.read()
    except FileNotFoundError:
        logger.warning(f"personal_info.md 未找到: {PERSONAL_INFO_PATH}")
        return DEFAULT_GOALS

    source_hash = _hash_source(source_text)

    # 检查缓存
    if not force_refresh:
        cached = get_career_goals()
        if cached and cached.get("source_hash") == source_hash:
            logger.info("职业目标缓存命中")
            return cached["goals"]

    # 加载 system prompt
    prompt_path = BASE_DIR / "prompts" / "career_goal_prompt.txt"
    with open(prompt_path, "r", encoding="utf-8") as f:
        system_prompt = f.read()

    # 调用 DeepSeek
    try:
        response = chat(system_prompt, source_text)
        cleaned = response.strip().strip("```json").strip("```").strip()
        goals = json.loads(cleaned)
        goals = _validate_goals(goals)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"职业目标提取失败: {e}，使用 {PERSONAL_INFO_PATH}")
        goals = _fallback_goals(source_text)

    # 缓存
    upsert_career_goals(json.dumps(goals, ensure_ascii=False), source_hash)
    logger.info(f"职业目标已缓存: {goals.get('role')} | 领域: {goals.get('domains')}")

    return goals


def _validate_goals(result: dict) -> dict:
    validated = {}
    validated["role"] = result.get("role", DEFAULT_GOALS["role"])
    validated["domains"] = (result.get("domains") or [])[:5]
    validated["skills_to_build"] = (result.get("skills_to_build") or [])[:5]
    validated["target_industries"] = (result.get("target_industries") or [])[:3]
    validated["target_companies"] = (result.get("target_companies") or [])[:3]
    validated["career_stage"] = result.get("career_stage", DEFAULT_GOALS["career_stage"])
    validated["summary"] = result.get("summary", DEFAULT_GOALS["summary"])
    return validated


def _fallback_goals(source_text: str) -> dict:
    """当 DeepSeek 提取失败时，基于关键词做简单提取"""
    goals = dict(DEFAULT_GOALS)
    goals["summary"] = "基于关键词自动提取（AI提取失败）"

    # 尝试匹配岗位
    if "财务信息化" in source_text or "财务产品" in source_text:
        goals["role"] = "财务信息化产品经理"
        goals["domains"] = ["财务共享", "AI应用", "ERP", "企业服务"]
    elif "AI产品" in source_text:
        goals["role"] = "AI产品经理"

    # 提取技能
    skills = []
    if "Python" in source_text:
        skills.append("Python")
    if "SQL" in source_text:
        skills.append("SQL")
    if "Dify" in source_text or "Agent" in source_text:
        skills.append("AI Agent开发")
    if "AI" in source_text or "大模型" in source_text:
        skills.append("大模型应用")
    goals["skills_to_build"] = skills

    # 目标行业
    if "阿里巴巴" in source_text or "网易" in source_text:
        goals["target_industries"] = ["互联网", "企业服务"]
        goals["target_companies"] = ["大型互联网公司"]

    return goals
