"""消息推送 — 企微通知 + 桌面通知 + SQLite 持久化 + 格式化输出"""
import json
import logging
import os
import subprocess
import uuid
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent
load_dotenv(BASE_DIR / "config" / ".env")

# 企微 access_token 缓存
_wx_token = None
_wx_token_expire = 0


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
    """格式化外部发现摘要，含原文链接"""
    if not recommendations:
        return ""

    top = recommendations[:5]
    lines = [f"🌐 全网搜集 · {len(recommendations)} 篇\n"]
    for i, r in enumerate(top):
        star = "⭐" if r.get("score", 0) >= 80 else "🔵" if r.get("score", 0) >= 70 else "📎"
        url = r.get("url", "")
        title = r.get("title", url)[:80]
        reason = r.get("reason", "")[:120]
        lines.append(f"{star} [{r.get('score', 0)}分] {title}")
        if reason:
            lines.append(f"   {reason}")
        if url:
            lines.append(f"   🔗 {url[:200]}")
        lines.append("")
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

    lines = [f"📖 知识库精华回顾 · {len(items)} 篇\n"]
    for i, item in enumerate(items):
        score = item.get("score", 0)
        star = "⭐" if score >= 0.8 else "🔵" if score >= 0.6 else "📎"
        title = item.get("title", "无标题")[:60]
        reason = item.get("reason", "")[:100]
        lines.append(f"{star} [{score*100:.0f}%] {title}")
        lines.append(f"   {reason}")
        lines.append("")
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
    print()


# ── 企业微信推送 ──

def _get_wecom_access_token() -> str:
    """获取企业微信 access_token（带缓存）"""
    global _wx_token, _wx_token_expire
    now = int(time.time())
    if _wx_token and now < _wx_token_expire:
        return _wx_token

    corpid = os.getenv("WECOM_CORP_ID", "")
    secret = os.getenv("WECOM_CORP_SECRET", "")
    if not corpid or not secret:
        logger.debug("企微配置缺失，跳过推送")
        return ""

    try:
        url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
        resp = requests.get(url, params={"corpid": corpid, "corpsecret": secret}, timeout=10)
        data = resp.json()
        _wx_token = data.get("access_token", "")
        _wx_token_expire = now + int(data.get("expires_in", 7200)) - 300
        logger.debug(f"企微 access_token 已获取")
        return _wx_token
    except Exception as e:
        logger.warning(f"获取企微 token 失败: {e}")
        return ""


def notify_email(title: str, body: str) -> bool:
    """发送邮件通知（通过 SMTP，不受 IP 白名单限制）"""
    import smtplib
    from email.mime.text import MIMEText

    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    notify_to = os.getenv("NOTIFY_EMAIL", smtp_user)

    if not all([smtp_host, smtp_user, smtp_pass]):
        logger.warning("SMTP 未配置，跳过邮件通知")
        return False

    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = title
        msg["From"] = smtp_user
        msg["To"] = notify_to

        if smtp_port == 465:
            import ssl
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15, context=ctx) as server:
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)

        logger.info(f"邮件已发送: {title}")
        return True
    except Exception as e:
        logger.warning(f"邮件发送失败: {e}")
        return False


def _get_kf_user_id() -> str:
    """获取微信客服的用户 ID（从最近一次收发消息中保存的）"""
    user_file = BASE_DIR / "data" / ".kf_user_id"
    if user_file.exists():
        uid = user_file.read_text().strip()
        if uid and uid != "unknown":
            return uid
    return ""


def notify_wechat_kf(title: str, body: str) -> bool:
    """通过微信客服发送消息到个人微信"""
    user_id = _get_kf_user_id()
    if not user_id:
        logger.debug("未找到微信客服用户 ID")
        return False

    corpid = os.getenv("WECOM_CORP_ID", "")
    corpsecret = os.getenv("WECOM_CORP_SECRET", "") or os.getenv("WECOM_KF_SECRET", "")
    kf_id = os.getenv("WECOM_KF_OPEN_ID", "")

    if not all([corpid, corpsecret, kf_id]):
        logger.debug("微信客服配置不完整")
        return False

    try:
        # 1. 获取 access_token
        token_url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={corpid}&corpsecret={corpsecret}"
        token_resp = requests.get(token_url, timeout=10)
        token = token_resp.json().get("access_token", "")

        if not token:
            return False

        # 2. 发送消息
        import uuid
        msg = f"{title}\n\n{body}"
        resp = requests.post(
            f"https://qyapi.weixin.qq.com/cgi-bin/kf/send_msg?access_token={token}",
            json={
                "touser": user_id,
                "open_kfid": kf_id,
                "msgid": str(uuid.uuid4()).replace("-", "")[:32],
                "msgtype": "text",
                "text": {"content": msg[:2000]},
            },
            timeout=15,
        )
        result = resp.json()
        if result.get("errcode") == 0:
            logger.info(f"微信客服推送成功: {title}")
            return True
        else:
            logger.warning(f"微信客服推送失败(errcode={result.get('errcode')}): {result.get('errmsg','')}")
            return False
    except Exception as e:
        logger.warning(f"微信客服推送异常: {e}")
        return False


def notify(title: str, body: str) -> bool:
    """统一通知入口：微信客服 → 邮件兜底"""
    if notify_wechat_kf(title, body):
        return True
    return notify_email(title, body)


def notify_wecom_textcard(title: str, description: str, url: str = "") -> bool:
    """发送企业微信文本卡片消息（需要本机 IP 在企微白名单内）"""
    token = _get_wecom_access_token()
    if not token:
        return False

    agent_id = os.getenv("WECOM_AGENT_ID", "")
    if not agent_id:
        return False

    try:
        body = {
            "touser": "@all", "msgtype": "textcard", "agentid": int(agent_id),
            "textcard": {
                "title": title[:80], "description": description[:500],
                "url": url or "https://work.weixin.qq.com",
            },
        }
        resp = requests.post(
            f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}",
            json=body, timeout=10,
        )
        result = resp.json()
        if result.get("errcode") == 0:
            logger.info(f"企微推送成功: {title}")
            return True
        else:
            logger.warning(f"企微推送失败(errcode={result.get('errcode')}): {result.get('errmsg','')}")
            return False
    except Exception as e:
        logger.warning(f"企微推送异常: {e}")
        return False


def notify_wecom_discovery(recommendations: list[dict]) -> bool:
    """推送 Discovery 发现结果"""
    if not recommendations:
        return False

    top = recommendations[:5]
    desc_lines = [f"共发现 {len(recommendations)} 条新内容\n"]
    for i, r in enumerate(top):
        star = "⭐" if r.get("score", 0) >= 80 else "🔵" if r.get("score", 0) >= 70 else "📎"
        url = r.get("url", "")
        desc_lines.append(f"{star} [{r.get('score', 0)}分] {r.get('title', '')[:60]}")
        if r.get("reason"):
            desc_lines.append(f"   {r['reason'][:100]}")
        if url:
            desc_lines.append(f"   🔗 {url[:200]}")
        desc_lines.append("")

    title = f"🆕 发现 {len(recommendations)} 条新内容"
    description = "\n".join(desc_lines)
    return notify(title, description)


def notify_wecom_internal(items: list[dict]) -> bool:
    """企微推送内部推荐结果"""
    if not items:
        return False

    top = items[:5]
    desc_lines = []
    for i, item in enumerate(top):
        score = item.get("score", 0)
        star = "⭐" if score >= 0.8 else "🔵" if score >= 0.6 else "📎"
        title = item.get("title", "无标题")[:60]
        reason = item.get("reason", "")[:80]
        desc_lines.append(f"{star} [{score*100:.0f}%] {title}")
        desc_lines.append(f"   {reason}")

    title = f"📚 知识库今日精选 {len(items)} 条"
    description = "\n".join(desc_lines)

    return notify_wecom_textcard(title, description)
