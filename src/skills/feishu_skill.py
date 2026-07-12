"""飞书多维表格读写 — v3：支持读取表格记录和飞书文档"""
import os
import json
import logging
import time
import requests
from dotenv import load_dotenv
from pathlib import Path

logger = logging.getLogger(__name__)

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


def read_bitable_records(page_size: int = 100) -> list[dict]:
    """从飞书多维表格读取所有记录"""
    token = get_tenant_access_token()
    app_token = os.getenv("FEISHU_APP_TOKEN")
    table_id = os.getenv("FEISHU_TABLE_ID")
    if not all([token, app_token, table_id]):
        logger.warning("飞书配置不完整，无法读取表格")
        return []

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    all_records = []
    page_token = None

    while True:
        url = (
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}"
            f"/tables/{table_id}/records?page_size={page_size}"
        )
        if page_token:
            url += f"&page_token={page_token}"

        resp = requests.get(url, headers=headers, timeout=30)
        data = resp.json()

        if data.get("code") != 0:
            logger.warning(f"飞书表格读取失败: {data}")
            break

        items = data.get("data", {}).get("items", [])
        for item in items:
            fields = item.get("fields", {})
            all_records.append({
                "id": fields.get("id", ""),
                "full_content": fields.get("full_content", ""),
                "category": fields.get("category", ""),
                "created_at": int(fields.get("created_at", 0)),
            })

        if data.get("data", {}).get("has_more"):
            page_token = data["data"].get("page_token", "")
        else:
            break

    logger.info(f"飞书表格读取: {len(all_records)} 条记录")
    return all_records


def read_feishu_doc_content(doc_url: str) -> str:
    """读取飞书文档内容（通过 doc token 或 URL）"""
    token = get_tenant_access_token()
    if not token:
        return ""

    # 从 URL 提取 doc_token
    doc_token = ""
    if "docs.feishu.cn" in doc_url or "feishu.cn/docx" in doc_url:
        import re
        m = re.search(r'/([A-Za-z0-9_-]{20,})', doc_url)
        if m:
            doc_token = m.group(1)

    if not doc_token:
        logger.warning(f"无法从 URL 提取 doc_token: {doc_url[:50]}")
        return ""

    try:
        headers = {"Authorization": f"Bearer {token}"}
        url = f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_token}/raw_content"
        resp = requests.get(url, headers=headers, timeout=15)
        data = resp.json()

        if data.get("code") == 0:
            content = data.get("data", {}).get("content", "")
            logger.info(f"飞书文档读取成功: {len(content)} 字符")
            return content
        else:
            logger.warning(f"飞书文档读取失败: {data}")
            return ""
    except Exception as e:
        logger.warning(f"飞书文档读取异常: {e}")
        return ""


def sync_feishu_to_sqlite() -> int:
    """将飞书表格中的记录同步到本地 SQLite（补充数据源）"""
    from knowledge.sqlite_store import insert_item as sqlite_add

    records = read_bitable_records()
    if not records:
        return 0

    new_count = 0
    for rec in records:
        rid = rec.get("id", "")
        if not rid or not rec.get("full_content"):
            continue

        # 检查是否已存在
        from knowledge.sqlite_store import _get_conn
        conn = _get_conn()
        existing = conn.execute(
            "SELECT id FROM knowledge_items WHERE id = ?", (rid,)
        ).fetchone()
        if existing:
            continue

        item = {
            "id": rid,
            "title": rec.get("full_content", "")[:100].split("\n")[0][:80],
            "summary": rec.get("full_content", "")[:500],
            "full_content": rec.get("full_content", ""),
            "category": rec.get("category", "未分类"),
            "tags": [],
            "source_type": "feishu_bitable",
            "source_path": "飞书多维表格",
            "created_at": rec.get("created_at", int(time.time() * 1000)),
        }
        if sqlite_add(item):
            new_count += 1

    logger.info(f"飞书→SQLite 同步: {new_count} 条新增")
    return new_count


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
