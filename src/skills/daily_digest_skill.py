"""每日汇总推送 — 合并知识库回顾 + 网络发现，一条消息"""
import logging
from skills.delivery_skill import notify_wechat_kf, notify_email

logger = logging.getLogger(__name__)


def send_daily_digest() -> bool:
    from knowledge.sqlite_store import (
        get_recommendations, get_internal_recommendations, _get_conn,
    )
    import time

    today_start = int(time.time()) - 86400
    conn = _get_conn()

    # 1. 外部发现 TOP 3
    ext_items = get_recommendations(limit=30, delivered_only=True)
    ext_recent = [r for r in ext_items if r.get("recommended_at", 0) > today_start]

    # 2. 内部推荐 TOP 3（带原始标题）
    int_items = get_internal_recommendations(limit=10)
    int_recent = [r for r in int_items if r.get("created_at", 0) > today_start]

    if not ext_recent and not int_recent:
        logger.info("今日无新推荐，跳过汇总推送")
        return False

    lines = ["📋 AIOS 每日精选\n"]

    if int_recent:
        lines.append("━━━ 📖 知识库回顾 ━━━")
        for r in int_recent[:3]:
            score = r.get("score", 0)
            star = "⭐" if score >= 0.8 else "🔵" if score >= 0.6 else "📎"
            item_id = r.get("item_id", "")

            # 从知识库查原标题
            row = conn.execute(
                "SELECT title FROM knowledge_items WHERE id = ?", (item_id,)
            ).fetchone()
            title = row["title"] if row else r.get("reason", "")[:60]
            reason = r.get("reason", "")[:80]

            lines.append(f"{star} [{score*100:.0f}%] {title}")
            if reason and len(reason) < 60:
                lines.append(f"   {reason}")

    if ext_recent:
        if int_recent:
            lines.append("")
        lines.append("━━━ 🆕 网络发现 ━━━")
        for r in ext_recent[:3]:
            score = r.get("score", 0)
            star = "⭐" if score >= 80 else "🔵" if score >= 70 else "📎"
            title = r.get("title", "")[:60]
            url = r.get("url", "")
            lines.append(f"{star} [{score}分] {title}")
            if url:
                lines.append(f"   🔗 {url[:150]}")

    body = "\n".join(lines)[:2000]

    if notify_wechat_kf("📋 AIOS 每日精选", body):
        logger.info("每日汇总推送成功（微信客服）")
        return True

    if notify_email("📋 AIOS 每日精选", body):
        logger.info("每日汇总推送成功（邮件）")
        return True

    return False
