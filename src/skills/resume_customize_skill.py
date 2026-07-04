"""简历定制 + 打招呼生成 — 基于 personal_info.md + JD"""
import json
import logging
from pathlib import Path
from models.deepseek_client import chat

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent
PERSONAL_INFO_PATH = Path("/Users/caimeiying/AI-Agent-Lab/skills/personal_info.md")


def _load_personal_info() -> str:
    """读取个人资料"""
    if PERSONAL_INFO_PATH.exists():
        return PERSONAL_INFO_PATH.read_text(encoding="utf-8")
    logger.warning(f"personal_info.md 不存在: {PERSONAL_INFO_PATH}")
    return ""


def customize(resume: dict, jd_text: str, match_result: dict, job_title: str = "",
              company: str = "", salary: str = "") -> dict:
    """为单个岗位生成个性化简历摘要 + 打招呼语

    Returns:
        {"customized_summary": "...", "greeting": "...", "jd_type": "B", "gaps": [...]}
    """
    personal_info = _load_personal_info()
    if not personal_info:
        return _fallback_customize(jd_text)

    prompt_path = BASE_DIR / "prompts" / "job_customize_resume_prompt.txt"
    with open(prompt_path, "r", encoding="utf-8") as f:
        system_prompt = f.read()

    # 追加打招呼模板指令
    system_prompt += _greeting_instructions()

    # 构建用户消息
    user_message = f"""【候选人详细资料】
{personal_info}

【目标岗位】
岗位名称: {job_title}
公司: {company}
薪资: {salary}

【JD全文】
{jd_text}

【匹配评分结果】
总分: {match_result.get('score', 0)}/100
匹配点: {json.dumps(match_result.get('match_points', []), ensure_ascii=False)}
差距点: {json.dumps(match_result.get('gap_points', []), ensure_ascii=False)}
评估: {match_result.get('overall_assessment', '')}
"""

    try:
        response = chat(system_prompt, user_message)
        cleaned = response.strip().strip("```json").strip("```").strip()
        result = json.loads(cleaned)
        return {
            "customized_summary": result.get("customized_summary", ""),
            "greeting": result.get("greeting", ""),
            "jd_type": result.get("jd_type", ""),
            "reordered_skills": result.get("reordered_skills", []),
            "experience_highlights": result.get("experience_highlights", []),
            "jd_keyword_gaps": result.get("jd_keyword_gaps", []),
            "resume_customizations": result.get("resume_customizations", []),
        }
    except Exception as e:
        logger.warning(f"简历定制失败: {e}")
        return _fallback_customize(jd_text)


def batch_customize(resume: dict, top_jobs: list[tuple]) -> list[dict]:
    """批量处理 TOP N 岗位，每个返回定制结果"""
    results = []
    for score, detail, match_result in top_jobs:
        logger.info(f"定制简历: {detail.title} @ {detail.company} ({score}分)")
        custom = customize(
            resume=resume,
            jd_text=detail.jd_text,
            match_result=match_result or {},
            job_title=detail.title,
            company=detail.company,
            salary=detail.salary or "",
        )
        results.append({
            "score": score,
            "title": detail.title,
            "company": detail.company,
            "salary": detail.salary,
            "url": detail.url,
            "match_points": (match_result or {}).get("match_points", []),
            "gap_points": (match_result or {}).get("gap_points", []),
            **custom,
        })
    return results


def _greeting_instructions() -> str:
    """追加打招呼模板指令到 prompt 中"""
    return """

## 额外输出：打招呼消息 + JD类型判断

除上述JSON字段外，还需额外输出以下字段：

1. **jd_type**: 判断JD属于哪种类型（A资金/B财务中台/C AI产品/D风控审核/E ERP业财）
2. **greeting**: 生成Boss直聘打招呼消息（手机一屏以内），模板：
   "老师您好，我对您提供的岗位非常有兴趣，附上我的简历供您了解～
   我是[目标岗位方向]（[B端年限]），[选3-4个最匹配JD的能力点简述]。
   我在2025年11月因公司属地政策与字节协商一致离职，离职后GAP期间考取雅思7分、学习Python/Tableau等数据分析工具、使用Dify搭建个人AI Agent工作流。欢迎您随时沟通[握手]"

**打招呼规则：**
- 必须从 personal_info.md 中提取真实数据，不编造
- 能力点选最匹配JD的3-4个，用量化数据（如"82%免审率""15→5人天"）
- GAP期描述固定使用上面模板中的内容
- 控制在手机一屏内（约150字）
- JD是AI方向时，强调AI落地经验和GAP期AI持续学习
"""


def _fallback_customize(jd_text: str) -> dict:
    return {
        "customized_summary": "",
        "greeting": "",
        "jd_type": "",
        "reordered_skills": [],
        "experience_highlights": [],
        "jd_keyword_gaps": [],
        "resume_customizations": [],
    }
