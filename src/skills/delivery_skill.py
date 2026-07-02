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
