"""内部推荐核心算法 — 五维打分 + MMR 精选

评分公式:
FINAL_SCORE = 0.40 × 内容相似度 + 0.30 × 职业加权 + 0.15 × 时间新鲜度
            - 0.10 × 互动惩罚 + 0.05 × 多样性加分
"""
import json
import logging
import math
import time
from pathlib import Path

from models.deepseek_client import chat

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent

# 权重配置
W_CONTENT = 0.40
W_CAREER = 0.30
W_RECENCY = 0.15
W_ENGAGEMENT_PENALTY = 0.10
W_DIVERSITY = 0.05

# MMR lambda（相关性 vs 多样性，越大越偏向相关性）
MMR_LAMBDA = 0.7

# 推荐阈值
MIN_SCORE = 0.15

# 元分类分组（用于多样性保证）
META_CATEGORIES = {
    "科技与AI": "tech",
    "产品与工具": "tech",
    "效率方法": "tech",
    "技术编程": "tech",
    "自然科学": "tech",
    "职场与创业": "career",
    "投资与商业": "career",
    "数据与报告": "career",
    "阅读与影视": "humanities",
    "人文与哲学": "humanities",
    "社会与热点": "humanities",
    "生活与旅行": "life",
    "健康与心理": "life",
    "美食与消费": "life",
    "人际关系": "life",
    "趣味与娱乐": "life",
    "医学健康": "life",
    "个人成长": "growth",
    "教育与学习": "growth",
    "设计与创意": "design",
    "其他": "other",
}


def score_candidates(
    candidates: list[dict],
    interest_profile: dict,
    career_goals: dict,
    interaction_stats: dict | None = None,
) -> list[dict]:
    """对所有候选项进行五维打分，返回带分数的列表"""
    if not candidates:
        return []

    now = int(time.time())
    liked = set(interaction_stats.get("liked_items", []) if interaction_stats else [])
    skipped = set(interaction_stats.get("skipped_items", []) if interaction_stats else [])

    # 1. 内容相似度：用兴趣画像文本做向量检索
    profile_text = interest_profile.get("interest_summary", "")
    if not profile_text:
        top_cats = interest_profile.get("preferred_categories", [])
        profile_text = " ".join(top_cats) if top_cats else ""

    vector_scores = _compute_vector_scores(candidates, profile_text)

    # 2. 职业加权：DeepSeek 批量打分（每批5条）
    career_scores = _compute_career_scores(candidates, career_goals)

    # 3. 组合分数
    scored = []
    preferred_cats = set(interest_profile.get("preferred_categories", []))

    for item in candidates:
        item_id = item.get("id", "")
        created = item.get("created_at", 0)

        # 内容相似度（0-1）
        content_sim = vector_scores.get(item_id, 0.0)
        cat = item.get("category", "")
        if cat in preferred_cats:
            content_sim += 0.1
        elif _get_meta_category(cat) == _get_meta_category(
            next(iter(preferred_cats), "")
        ):
            content_sim += 0.05
        content_sim = min(content_sim, 1.0)

        # 职业加权（0-1）
        career = career_scores.get(item.get("title", ""), 0.0) / 100.0

        # 时间新鲜度（0-1）
        # created_at 可能为秒或毫秒时间戳，统一处理
        created_sec = created / 1000 if created > 1e12 else created
        days_since = (now - created_sec) / 86400 if created_sec > 0 else 365
        clamped_days = max(0, min(days_since, 1000))
        recency = math.exp(-0.01 * clamped_days)

        # 互动惩罚（0-1）
        penalty = 0.0
        if item_id in skipped:
            penalty += 0.6
        if item_id in liked:
            penalty += 0.3
        penalty = min(penalty, 1.0)

        # 基础得分
        base_score = (
            W_CONTENT * content_sim
            + W_CAREER * career
            + W_RECENCY * recency
            - W_ENGAGEMENT_PENALTY * penalty
        )

        # 可操作性加分
        if item.get("actionable"):
            base_score += 0.05

        # 高质量来源加分
        if item.get("source_quality") == "high":
            base_score += 0.03

        scored.append({
            **item,
            "_content_sim": content_sim,
            "_career_boost": career,
            "_recency": recency,
            "_engagement_penalty": penalty,
            "_diversity_bonus": 0.0,
            "score": round(base_score, 4),
        })

    return scored


def select_top_k(scored_items: list[dict], k: int = 5) -> list[dict]:
    """MMR 贪心精选 Top K，保证类别多样性"""
    if len(scored_items) <= k:
        return sorted(scored_items, key=lambda x: x["score"], reverse=True)

    remaining = list(scored_items)
    selected = []

    for _ in range(k):
        best_item = None
        best_mmr = -float("inf")

        for item in remaining:
            relevance = item["score"]
            # 与已选条目的最大相似度
            max_sim = 0.0
            if selected:
                for s in selected:
                    sim = _item_similarity(item, s)
                    max_sim = max(max_sim, sim)

            mmr = MMR_LAMBDA * relevance - (1 - MMR_LAMBDA) * max_sim

            if mmr > best_mmr:
                best_mmr = mmr
                best_item = item

        if best_item:
            remaining.remove(best_item)
            # 多样性加分
            best_item["_diversity_bonus"] = (1 - MMR_LAMBDA) * (1 - best_mmr / (best_item["score"] + 0.001))
            best_item["score"] = round(best_item["score"] + W_DIVERSITY * best_item["_diversity_bonus"], 4)
            selected.append(best_item)

    return selected


def generate_reasons(items: list[dict], career_goals: dict) -> list[dict]:
    """为推荐条目生成一句话推荐理由"""
    if not items:
        return items

    role = career_goals.get("role", "产品经理")
    domains = "、".join(career_goals.get("domains", [])[:3])

    prompt_path = BASE_DIR / "prompts" / "internal_recommendation_prompt.txt"
    with open(prompt_path, "r", encoding="utf-8") as f:
        system_prompt = f.read()

    # 构建条目列表
    items_text = "\n---\n".join(
        f"条目{i+1}:\n标题: {item.get('title', '')}\n分类: {item.get('category', '')}\n标签: {', '.join(item.get('tags', [])[:5])}\n摘要: {(item.get('summary') or '')[:150]}"
        for i, item in enumerate(items)
    )

    user_message = f"用户职业目标：岗位={role}，领域={domains}\n\n待评分条目：\n{items_text}"

    try:
        response = chat(system_prompt, user_message)
        cleaned = response.strip().strip("```json").strip("```").strip()
        result = json.loads(cleaned)
        scores_list = result.get("scores", [])

        for i, item in enumerate(items):
            if i < len(scores_list):
                item["reason"] = scores_list[i].get("reason", "与你的知识体系相关")
                # 如果DeepSeek给出的分数比我们算的高，略微修正
                ds_score = scores_list[i].get("score", 0) / 100.0
                if ds_score > 0:
                    item["score"] = round(item["score"] * 0.7 + ds_score * 0.3, 4)
            else:
                item["reason"] = "与你的知识体系相关"
    except Exception as e:
        logger.warning(f"推荐理由生成失败: {e}")
        for item in items:
            if "reason" not in item:
                cat = item.get("category", "")
                item["reason"] = f"知识库中的{cat}类内容"

    return items


# ── 内部函数 ──

def _compute_vector_scores(candidates: list[dict], query_text: str) -> dict[str, float]:
    """多维度 RAG 评分：用画像中的多个 rag_dimensions 分别检索，加权融合"""
    scores = {}
    if not query_text:
        return scores

    # 尝试加载多维度画像
    try:
        from skills.keyword_profile_skill import load_rag_dimensions
        dimensions = load_rag_dimensions()
    except Exception:
        dimensions = []

    if not dimensions:
        # 降级：单查询
        return _single_vector_search(candidates, query_text)

    # 多维度检索 + 加权融合
    from knowledge.rag_retriever import hybrid_search
    dim_scores = {}
    for dim in dimensions:
        dim_name = dim.get("name", "")
        dim_query = dim.get("query", "")
        dim_weight = dim.get("weight", 0.25)
        try:
            results = hybrid_search(dim_query, top_k=min(30, len(candidates)))
            for r in results:
                rid = r.get("id", "")
                sim = r.get("similarity_score", 0) or 0
                if rid not in dim_scores:
                    dim_scores[rid] = []
                dim_scores[rid].append(sim * dim_weight)
        except Exception as e:
            logger.debug(f"维度 '{dim_name}' 检索失败: {e}")

    for rid, weighted_sims in dim_scores.items():
        scores[rid] = round(sum(weighted_sims), 4)

    return scores


def _single_vector_search(candidates: list[dict], query_text: str) -> dict[str, float]:
    """降级：单查询向量检索"""
    scores = {}
    try:
        from knowledge.rag_retriever import hybrid_search
        results = hybrid_search(query_text, top_k=min(30, len(candidates)))
        for r in results:
            rid = r.get("id", "")
            sim = r.get("similarity_score", 0)
            if sim is not None:
                scores[rid] = sim
    except Exception as e:
        logger.warning(f"向量检索失败: {e}")
    return scores


def _compute_career_scores(candidates: list[dict], career_goals: dict) -> dict[str, float]:
    """使用 DeepSeek 批量评估职业相关性（每批5条，最多处理15条以节省API成本）"""
    scores = {}
    if not career_goals or not candidates:
        return scores

    # 先做关键词粗筛，只对最相关的候选调用DeepSeek
    domain_keywords = set()
    for d in career_goals.get("domains", []):
        for w in d.lower().split():
            domain_keywords.add(w)
    for s in career_goals.get("skills_to_build", []):
        for w in s.lower().split():
            domain_keywords.add(w)

    pre_scored = []
    for item in candidates:
        pre_score = 25.0
        text = f"{item.get('title', '')} {item.get('category', '')} {' '.join(item.get('tags', []))}".lower()
        for kw in domain_keywords:
            if kw and kw in text:
                pre_score += 10
        pre_scored.append((item, pre_score))

    pre_scored.sort(key=lambda x: x[1], reverse=True)
    top_candidates = [item for item, _ in pre_scored[:15]]

    prompt_path = BASE_DIR / "prompts" / "internal_recommendation_prompt.txt"
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            system_prompt = f.read()
    except FileNotFoundError:
        logger.warning("internal_recommendation_prompt.txt 未找到")
        return _fallback_career_scores(candidates, career_goals)

    role = career_goals.get("role", "")
    domains = "、".join(career_goals.get("domains", [])[:3])
    skills = "、".join(career_goals.get("skills_to_build", [])[:3])

    batch_size = 5
    for batch_start in range(0, len(top_candidates), batch_size):
        batch = top_candidates[batch_start:batch_start + batch_size]

        items_text = "\n---\n".join(
            f"条目{i+1}:\n标题: {item.get('title', '')}\n分类: {item.get('category', '')}\n标签: {', '.join(item.get('tags', [])[:5])}\n摘要: {(item.get('summary') or '')[:150]}"
            for i, item in enumerate(batch)
        )
        user_message = f"用户职业目标：岗位={role}，领域={domains}，目标技能={skills}\n\n待评分条目：\n{items_text}"

        try:
            response = chat(system_prompt, user_message)
            cleaned = response.strip().strip("```json").strip("```").strip()
            result = json.loads(cleaned)
            for s in result.get("scores", []):
                title = s.get("title", "")
                score_val = s.get("score", 0)
                if title:
                    scores[title] = float(score_val)
        except Exception as e:
            logger.warning(f"职业评分批次失败: {e}")

    # 未评分的候选用关键词降级打分
    fallback = _fallback_career_scores(
        [c for c in candidates if c.get("title", "") not in scores],
        career_goals,
    )
    scores.update(fallback)

    return scores


def _fallback_career_scores(candidates: list[dict], career_goals: dict) -> dict[str, float]:
    """降级：基于关键词匹配的简单职业评分"""
    scores = {}
    for item in candidates:
        title = item.get("title", "")
        tags = [t.lower() for t in item.get("tags", [])]
        cat = item.get("category", "")
        text = f"{title} {cat} {' '.join(tags)}".lower()

        simple_score = 25.0
        for domain in career_goals.get("domains", []):
            for w in domain.lower().split():
                if w and w in text:
                    simple_score += 15
                    break
        for skill in career_goals.get("skills_to_build", []):
            for w in skill.lower().split():
                if w and w in text:
                    simple_score += 10
                    break

        scores[title] = min(simple_score, 100.0)
    return scores


def _get_meta_category(category: str) -> str:
    return META_CATEGORIES.get(category, "other")


def _item_similarity(item_a: dict, item_b: dict) -> float:
    """计算两个条目的相似度（用于MMR多样性惩罚）"""
    sim = 0.0
    # 同分类 +0.3
    if item_a.get("category") == item_b.get("category"):
        sim += 0.3
    # 同元分类 +0.15
    if _get_meta_category(item_a.get("category", "")) == _get_meta_category(item_b.get("category", "")):
        sim += 0.15
    # 标签重叠
    tags_a = set(item_a.get("tags", []))
    tags_b = set(item_b.get("tags", []))
    if tags_a and tags_b:
        overlap = len(tags_a & tags_b) / max(len(tags_a | tags_b), 1)
        sim += overlap * 0.2
    return min(sim, 1.0)
