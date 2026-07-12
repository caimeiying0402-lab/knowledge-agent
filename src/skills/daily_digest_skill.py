"""每日汇总推送 — 合并知识库回顾 + 网络发现，一条微信消息"""
import logging
from skills.delivery_skill import notify_wechat_kf, notify_email

logger = logging.getLogger(__name__)


def send_daily_digest() -> bool:
    """查询今天已保存但未推送的推荐，汇总成一条消息发送"""
    from knowledge.sqlite_store import (
        get_recommendations,
        get_internal_recommendations,
        _get_conn,
    )
    import time

    today_start = int(time.time()) - 86400

    # 1. 外部发现 TOP 5
    ext_items = get_recommendations(limit=30, delivered_only=True)
    ext_recent = [r for r in ext_items if r.get("recommended_at", 0) > today_start]

    # 2. 内部推荐 TOP 5
    int_items = get_internal_recommendations(limit=10)
    int_recent = [r for r in int_items if r.get("created_at", 0) > today_start]

    if not ext_recent and not int_recent:
        logger.info("今日无新推荐，跳过汇总推送")
        return False

    # 构建汇总消息
    lines = ["📋 AIOS 每日精选\n"]

    if int_recent:
        lines.append("━━━ 📖 知识库回顾 ━━━")
        for i, r in enumerate(int_recent[:3]):
            score = r.get("score", 0)
            star = "⭐" if score >= 0.8 else "🔵" if score >= 0.6 else "📎"
            reason = r.get("reason", "")[:80]
            lines.append(f"{star} [{score*100:.0f}%] {reason}")

    if ext_recent:
        lines.append("")
        lines.append("━━━ 🆕 网络发现 ━━━")
        for i, r in enumerate(ext_recent[:3]):
            score = r.get("score", 0)
            star = "⭐" if score >= 80 else "🔵" if score >= 70 else "📎"
            title = r.get("title", "")[:60]
            url = r.get("url", "")
            lines.append(f"{star} [{score}分] {title}")
            if url:
                lines.append(f"   🔗 {url[:150]}")

    body = "\n".join(lines)[:2000]

    # 微信客服推送
    if notify_wechat_kf("📋 AIOS 每日精选", body):
        logger.info("每日汇总推送成功（微信客服）")
        return True

    # 邮件兜底
    if notify_email("📋 AIOS 每日精选", body):
        logger.info("每日汇总推送成功（邮件）")
        return True

    return False
