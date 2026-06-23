"""飞书多维表格写入 — v2：支持 highlights 嵌入"""
import os
import logging
import requests
from dotenv import load_dotenv
from pathlib import Path

logger = logging.getLogger(__name__)

# 项目根目录
base_dir = Path(__file__).parent.parent.parent
env_path = base_dir / "config" / ".env"
load_dotenv(env_path)


def get_tenant_access_token():
    """获取飞书应用的 tenant_access_token"""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    payload = {
        "app_id": os.getenv("FEISHU_APP_ID"),
        "app_secret": os.getenv("FEISHU_APP_SECRET")
    }
    res = requests.post(url, json=payload)
    return res.json()["tenant_access_token"]


def write_to_bitable(record: dict):
    """
    向飞书多维表格写入一条记录。

    Args:
        record: 包含字段的字典，额外支持 highlights 字段（会嵌入到 full_content 中）
    """
    token = get_tenant_access_token()
    app_token = os.getenv("FEISHU_APP_TOKEN")
    table_id = os.getenv("FEISHU_TABLE_ID")
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # ── 处理 highlights：嵌入到 full_content 头部 ──
    highlights = record.get("highlights", [])
    full_content = record.get("full_content", "")
    if highlights:
        highlights_section = "## 💡关键亮点\n" + "\n".join(f"• {h}" for h in highlights)
        full_content = f"{highlights_section}\n\n---\n\n{full_content}"

    # ── 增强 summary（v2）──
    summary = record.get("summary", "")
    # 如果有质量标签，追加到 summary 末尾
    source_quality = record.get("source_quality", "")
    actionable = record.get("actionable", None)
    if source_quality or actionable is not None:
        extras = []
        if source_quality:
            qmap = {"high": "⭐高可信", "medium": "●中等可信", "low": "○低可信"}
            extras.append(qmap.get(source_quality, source_quality))
        if actionable is True:
            extras.append("✓可执行")
        if extras:
            summary = f"{summary}  [{'; '.join(extras)}]"

    payload = {
        "fields": {
            "id": record.get("id", ""),
            "source_type": record.get("source_type", ""),
            "source_path": record.get("source_path", ""),
            "title": record.get("title", ""),
            "summary": summary,
            "full_content": full_content,
            "tags": record.get("tags", []),
            "category": record.get("category", ""),
            "embedding_status": record.get("embedding_status", False),
            "created_at": record.get("created_at", 0),
        }
    }

    res = requests.post(url, headers=headers, json=payload)
    return res.json()
