"""简历结构化解析 — 读取PDF/文本 → DeepSeek提取结构化JSON"""
import json
import logging
from pathlib import Path
import pdfplumber
from models.deepseek_client import chat

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent

DEFAULT_RESULT = {
    "personal": {
        "name": None, "target_role": [],
        "years_of_experience": None, "current_industry": None,
        "target_location": None, "salary_expectation": None
    },
    "core_competencies": {
        "domain_knowledge": [], "ai_expertise": [], "product_skills": []
    },
    "work_experience": [],
    "education": {"degree": None, "major": None, "school": None},
    "languages": {}
}


def extract_text_from_pdf(pdf_path: str) -> str:
    """使用 pdfplumber 提取 PDF 文本"""
    text_pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_pages.append(page_text)
    return "\n".join(text_pages)


def parse_resume(source: str, source_type: str = "text") -> dict:
    """
    解析简历，返回结构化JSON。

    Args:
        source: PDF文件路径 或 纯文本
        source_type: "pdf" | "text"

    Returns:
        与 resume_profile.json 同 schema 的 dict
    """
    # 1. 获取文本
    if source_type == "pdf":
        if not os.path.isfile(source):
            logger.error(f"PDF文件不存在: {source}")
            return DEFAULT_RESULT
        raw_text = extract_text_from_pdf(source)
    else:
        raw_text = source

    if not raw_text or not raw_text.strip():
        logger.warning("简历文本为空，返回默认结果")
        return DEFAULT_RESULT

    # 2. 加载 prompt
    prompt_path = BASE_DIR / "prompts" / "job_resume_prompt.txt"
    with open(prompt_path, "r", encoding="utf-8") as f:
        system_prompt = f.read()

    # 3. 调用 DeepSeek
    response = chat(system_prompt, raw_text)
    logger.debug(f"DeepSeek raw response:\n{response[:500]}")

    # 4. 解析 JSON
    try:
        cleaned = response.strip().strip("```json").strip("```").strip()
        result = json.loads(cleaned)
        return result
    except json.JSONDecodeError as e:
        logger.warning(f"JSON 解析失败: {e}, raw={response[:200]}")
        last_brace = response.rfind("}")
        if last_brace > 0:
            try:
                result = json.loads(response[:last_brace + 1])
                return result
            except json.JSONDecodeError:
                pass
        return DEFAULT_RESULT
