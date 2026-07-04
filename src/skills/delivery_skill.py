"""消息推送 — 桌面通知 + SQLite 持久化 + 格式化输出"""
import json
import logging
import subprocess
import uuid
import time
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent


def notify_desktop(title: str, message: str) -> bool:
    """macOS 桌面通知（osascript）"""
    try:
        clean_title = title.replace('"', "'").replace("\n", " ")
        clean_msg = message.replace('"', "'").replace("\n", " ")[:200]
        script = f'display notification "{clean_msg}" with title "{clean_title}" sound name "default"'
        subprocess.run(
            ["osascript", "-e", script],
            timeout=5,
            capture_output=True,
        )
        logger.info(f"桌面通知已发送: {title}")
        return True
    except Exception as e:
        logger.warning(f"桌面通知失败: {e}")
        return False


def save_recommendations(
    recommendations: list[dict],
    search_results: list[dict],
    interest_profile: dict,
) -> int:
    """保存推荐结果到 SQLite"""
    from knowledge.sqlite_store import insert_recommendation

    now = int(time.time())
    saved = 0

    # 构建 url -> search_result 映射，用于补充 snippet
    result_map = {r["url"]: r for r in search_results}

    for rec in recommendations:
        url = rec.get("url", "")
        sr = result_map.get(url, {})

        record = {
            "id": str(uuid.uuid4()),
            "url": url,
            "title": sr.get("title", "") or rec.get("title", ""),
            "snippet": sr.get("snippet", "") or "",
            "score": rec.get("score", 0),
            "reason": rec.get("reason", ""),
            "category_match": rec.get("category_match", ""),
            "interest_category": interest_profile.get("top_interests", [{}])[0].get("category", ""),
            "source_query": sr.get("source_query", ""),
            "full_content": sr.get("full_content", ""),
            "recommended_at": now,
            "delivered": True,
        }

        if insert_recommendation(record):
            saved += 1

    logger.info(f"推荐已保存: {saved}/{len(recommendations)} 条")
    return saved


def format_recommendation_message(recommendations: list[dict]) -> str:
    """格式化推荐摘要，用于桌面通知和终端输出"""
    if not recommendations:
        return "本次未发现新的推荐内容。"

    top = recommendations[:5]
    lines = [f"发现 {len(recommendations)} 条可能感兴趣的内容:\n"]
    for i, r in enumerate(top):
        star = "⭐" if r.get("score", 0) >= 80 else "🔵" if r.get("score", 0) >= 70 else "📎"
        lines.append(
            f"{star} [{r.get('score', 0)}分] {r.get('title', r.get('url', '无标题'))[:80]}\n"
            f"   {r.get('reason', '')[:120]}"
        )
    return "\n".join(lines)


def print_recommendations(recommendations: list[dict]) -> None:
    """终端友好输出推荐结果"""
    print("\n" + "=" * 60)
    print(format_recommendation_message(recommendations))
    print("=" * 60)
    for i, r in enumerate(recommendations[:10]):
        print(f"\n{'─' * 40}")
        print(f"#{i+1}  [{r.get('score', 0)}分] {r.get('title', '')}")
        print(f"    URL: {r.get('url', '')}")
        print(f"    理由: {r.get('reason', '')}")
        print(f"    分类: {r.get('category_match', '')}")
    print()


# ── 内部推荐（知识库已有内容推荐） ──

def notify_internal_recommendations(items: list[dict]) -> bool:
    """桌面通知：内部知识库推荐"""
    if not items:
        return False
    top = items[:3]
    lines = [f"[{item.get('score', 0):.0f}%] {item.get('title', '')[:50]}" for item in top]
    message = "\n".join(lines)
    return notify_desktop("Knowledge Agent - 今日推荐", message)


def save_internal_recommendations(
    items: list[dict], batch_id: str, triggered_by: str = "scheduled",
    gap_signals: list[dict] | None = None,
) -> int:
    """保存内部推荐结果到 SQLite"""
    from knowledge.sqlite_store import insert_internal_recommendation

    now = int(time.time())
    saved = 0

    gap_json = json.dumps(gap_signals, ensure_ascii=False) if gap_signals else None

    for item in items:
        record = {
            "id": str(uuid.uuid4()),
            "item_id": item.get("id", ""),
            "score": item.get("score", 0),
            "score_breakdown": json.dumps({
                "content_sim": item.get("_content_sim", 0),
                "career_boost": item.get("_career_boost", 0),
                "recency": item.get("_recency", 0),
                "engagement_penalty": item.get("_engagement_penalty", 0),
                "diversity_bonus": item.get("_diversity_bonus", 0),
            }, ensure_ascii=False),
            "reason": item.get("reason", ""),
            "triggered_by": triggered_by,
            "batch_id": batch_id,
            "gap_signals": gap_json,
            "delivered": 1,
            "created_at": now,
        }

        if insert_internal_recommendation(record):
            saved += 1

    logger.info(f"内部推荐已保存: {saved}/{len(items)} 条")
    return saved


def format_internal_recommendation_message(items: list[dict]) -> str:
    """格式化内部推荐摘要"""
    if not items:
        return "暂无可推荐内容。"

    lines = [f"知识库今日精选 {len(items)} 条:\n"]
    for i, item in enumerate(items):
        score = item.get("score", 0)
        star = "⭐" if score >= 0.8 else "🔵" if score >= 0.6 else "📎"
        title = item.get("title", "无标题")[:60]
        reason = item.get("reason", "")[:100]
        lines.append(f"{star} [{score*100:.0f}%] {title}\n   {reason}")
    return "\n".join(lines)


def print_internal_recommendations(items: list[dict]) -> None:
    """终端友好输出内部推荐结果"""
    print("\n" + "=" * 60)
    print(format_internal_recommendation_message(items))
    print("=" * 60)
    for i, item in enumerate(items[:10]):
        print(f"\n{'─' * 40}")
        print(f"#{i+1}  [{item.get('score', 0)*100:.0f}%] {item.get('title', '')}")
        print(f"    ID: {item.get('id', '')[:8]}")
        print(f"    理由: {item.get('reason', '')}")
        print(f"    分类: {item.get('category', '')}")
        print(f"    内容: {(item.get('content_sim', 0)*100):.0f}% | "
              f"职业: {(item.get('career_boost', 0)*100):.0f}% | "
              f"时间: {(item.get('recency', 0)*100):.0f}%")
    print()
