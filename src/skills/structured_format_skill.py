"""
structured_format_skill.py — 知识条目结构化格式化

将非结构化的 AI 摘要 + 原文按用户偏好重新整理为编号层级、极度精炼、
原文忠实的结构化输出。用于飞书多维表格展示。

输出规则：
  - 层级编号（1. 1.1 1.2 2. ...），法律条文风格
  - 每条 ≤80 字（硬上限 100 字）
  - 禁止 "这是/那是/不是...而是..." 等解释性句式
  - 原文事实不得篡改、不得添加、不得发挥
  - 无"亮点"/"关键点"/"总结"等元描述词
"""

import logging
from models.deepseek_client import chat

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是知识提炼引擎。将输入内容整理为结构化笔记。

## 格式规则
- 层级编号输出。顶级用 "1." "2." "3."，二级用 "1.1" "1.2"，以此类推。
- 每条一行，≤80字。极少数必要情况可到100字。
- 行 = 完整陈述。不拆句，不断句。

## 内容规则
- 严格保留原文事实。不添加原文没有的信息。
- 不推测，不发挥，不评价（不说"值得关注""很有启发"）。
- 不写"这是…""不是…而是…""核心在于…""主要体现在…"等分析框架句式。
- 只提取事实、观点、数据、逻辑关系。去掉修辞。

## 禁止词汇
亮点、关键点、核心、精髓、总结、概述、值得、启发、体现、彰显、诠释、印证、说明、这提醒我们、值得注意的是、可以发现

## 示例

输入：
"咖啡豆的烘焙程度决定了咖啡的风味。浅度烘焙保留更多花果酸香，深度烘焙则产生焦糖和苦味。不同产区豆子适合不同烘焙度。"

输出：
1. 烘焙程度决定咖啡风味
1.1 浅度烘焙 → 花果酸香保留多
1.2 深度烘焙 → 焦糖、苦味
2. 产区决定适宜烘焙度

输入：
"不要在重大选择上违背自己的意志。人在重大选择上违背意志时往往清醒而非迷茫。接受offer时知道不对劲但薪资更好看。这是在清醒中做违背自己的决定。"

输出：
1. 重大选择违背意志，多为清醒决策而非迷茫
1.1 接受offer时明知不对劲，因薪资妥协
2. 清醒中违背自己 → 背叛自我感受
3. 每次违背破坏与自己的信任关系"""


def format_structured(title: str, summary: str, highlights: list[str],
                      raw_content: str = "", tags: list[str] = None) -> str:
    """
    将知识条目格式化为用户偏好的结构化笔记。

    Args:
        title: 原标题
        summary: AI 生成的摘要
        highlights: AI 提取的亮点列表
        raw_content: 原始内容（文本/OCR结果/抓取页面）
        tags: 标签列表

    Returns:
        结构化文本（可直接作为飞书展示内容）
    """
    # 组装输入 — 优先传原文，AI 自己提炼
    parts = []

    if raw_content and len(raw_content) > 20:
        # 截断过长内容，保留足够上下文
        content_text = raw_content[:3000] if len(raw_content) > 3000 else raw_content
        parts.append(f"【原文】\n{content_text}")

    if summary and summary.strip():
        parts.append(f"【AI摘要（仅供参考，以原文为准）】\n{summary}")

    if highlights:
        parts.append(f"【候选要点】\n" + "\n".join(f"- {h}" for h in highlights))

    if tags:
        parts.append(f"【标签】{' '.join(tags)}")

    if title:
        parts.insert(0, f"标题：{title}")

    if not parts:
        return ""

    user_input = "\n\n".join(parts)

    try:
        result = chat(SYSTEM_PROMPT, user_input)

        if not result:
            return ""

        result = result.strip()

        # 清除可能的 markdown 代码块包装
        if result.startswith("```"):
            lines = result.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            result = "\n".join(lines)

        logger.info(f"结构化格式化完成: {len(result)} 字符, {result.count(chr(10))+1} 行")
        return result

    except Exception as e:
        logger.error(f"结构化格式化失败: {e}")
        # 降级：返回摘要+亮点的简单拼接
        fallback = []
        if summary:
            fallback.append(summary)
        if highlights:
            fallback.append("\n".join(f"• {h}" for h in highlights))
        return "\n\n".join(fallback)
