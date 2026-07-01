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

    Feishu 表格当前字段（5个）：
      id / full_content / category / embedding_status / created_at
    其余字段（source_type/source_path/title/summary/tags）写入 SQLite 日志，
    飞书表格不再存储冗余字段。
    """
    token = get_tenant_access_token()
    app_token = os.getenv("FEISHU_APP_TOKEN")
    table_id = os.getenv("FEISHU_TABLE_ID")
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # ── full_content = 结构化笔记（已由 structured_format_skill 生成）──
    full_content = record.get("full_content", "")

    payload = {
        "fields": {
            "id": record.get("id", ""),
            "full_content": full_content,
            "category": record.get("category", ""),
            "embedding_status": record.get("embedding_status", False),
            "created_at": record.get("created_at", 0),
        }
    }

    res = requests.post(url, headers=headers, json=payload)
    return res.json()
