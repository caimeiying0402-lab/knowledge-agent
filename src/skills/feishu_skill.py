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


def list_feishu_folder(folder_token: str) -> list[dict]:
    """列出飞书文件夹中的所有文件（文档/表格等）"""
    token = get_tenant_access_token()
    if not token:
        return []

    all_files = []
    page_token = ""

    try:
        while True:
            url = "https://open.feishu.cn/open-apis/drive/v1/files"
            params = {
                "folder_token": folder_token,
                "page_size": 50,
            }
            if page_token:
                params["page_token"] = page_token

            headers = {"Authorization": f"Bearer {token}"}
            resp = requests.get(url, headers=headers, params=params, timeout=15)
            data = resp.json()

            if data.get("code") != 0:
                logger.warning(f"飞书文件夹列表失败: {data}")
                break

            for f in data.get("data", {}).get("files", []):
                all_files.append({
                    "token": f.get("token", ""),
                    "name": f.get("name", ""),
                    "type": f.get("type", ""),  # docx, bitable, folder, etc.
                })

            if data.get("data", {}).get("has_more"):
                page_token = data["data"].get("page_token", "")
            else:
                break

        logger.info(f"飞书文件夹 [{folder_token}]: {len(all_files)} 个文件")
        return all_files
    except Exception as e:
        logger.warning(f"飞书文件夹列表异常: {e}")
        return []


def import_feishu_folder_to_sqlite(folder_token: str) -> int:
    """将飞书文件夹中的所有文档导入 SQLite 知识库"""
    from knowledge.sqlite_store import insert_item, _get_conn
    import uuid

    files = list_feishu_folder(folder_token)
    if not files:
        return 0

    new_count = 0
    for f in files:
        if f["type"] not in ("docx", "doc"):
            continue

        token_str = f["token"]
        # 检查已存在
        conn = _get_conn()
        existing = conn.execute(
            "SELECT id FROM knowledge_items WHERE source_path LIKE ?",
            (f"%{token_str}%",)
        ).fetchone()
        if existing:
            continue

        content = read_feishu_doc_by_token(token_str)
        if not content:
            continue

        # 构建知识条目
        title = f["name"]
        summary = content[:500]
        item_id = str(uuid.uuid4())

        # 简单分类（基于文件名关键词）
        category = "其他"
        name_lower = title.lower()
        if any(k in name_lower for k in ["ai", "llm", "agent", "rag", "大模型", "prompt"]):
            category = "科技与AI"
        elif any(k in name_lower for k in ["产品", "prd", "需求", "竞品", "原型"]):
            category = "产品与工具"
        elif any(k in name_lower for k in ["财务", "会计", "税务", "费控", "核算"]):
            category = "职场与创业"
        elif any(k in name_lower for k in ["面试", "简历", "求职", "职业"]):
            category = "职场与创业"
        elif any(k in name_lower for k in ["效率", "工具", "方法", "习惯"]):
            category = "效率方法"

        record = {
            "id": item_id,
            "title": title,
            "summary": summary,
            "full_content": content,
            "category": category,
            "tags": [],
            "source_type": "feishu_doc",
            "source_path": f"飞书文档: {token_str}",
            "created_at": int(time.time() * 1000),
        }
        if insert_item(record):
            new_count += 1

    logger.info(f"飞书文件夹导入: {new_count} 条新增（共 {len(files)} 个文件）")
    return new_count


def read_feishu_doc_by_token(doc_token: str) -> str:
    """通过 doc_token 直接读取飞书文档原始内容"""
    token = get_tenant_access_token()
    if not token:
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


def _extract_token_from_url(url: str) -> tuple[str, str]:
    """从飞书 URL 提取 (token, type)
    支持: /wiki/xxx, /docx/xxx, /docs/xxx, /drive/folder/xxx
    """
    import re
    # wiki 文档: https://my.feishu.cn/wiki/HBapwWqmZiQPvkkTr4kci6fKnse
    m = re.search(r'/wiki/([A-Za-z0-9_-]{10,})', url)
    if m:
        return m.group(1), "wiki"
    # docx 文档
    m = re.search(r'/docx/([A-Za-z0-9_-]{10,})', url)
    if m:
        return m.group(1), "docx"
    # docs 文档
    m = re.search(r'/docs/([A-Za-z0-9_-]{10,})', url)
    if m:
        return m.group(1), "doc"
    # drive folder
    m = re.search(r'/folder/([A-Za-z0-9_-]{10,})', url)
    if m:
        return m.group(1), "folder"
    # bitable/base: https://my.feishu.cn/base/PppsbADLlaneZVs6tUrcPfg2nef
    m = re.search(r'/base/([A-Za-z0-9_-]{10,})', url)
    if m:
        return m.group(1), "bitable"
    # 纯 token
    if re.match(r'^[A-Za-z0-9_-]{10,}$', url.strip()):
        return url.strip(), "unknown"
    return "", ""


def read_feishu_wiki_content(wiki_token: str) -> str:
    """读取飞书 Wiki/知识库 文档内容"""
    token = get_tenant_access_token()
    if not token:
        return ""

    # 先尝试 wiki API
    try:
        headers = {"Authorization": f"Bearer {token}"}
        # wiki v2 API: 获取节点信息
        info_url = f"https://open.feishu.cn/open-apis/wiki/v2/spaces/get_node?token={wiki_token}"
        info_resp = requests.get(info_url, headers=headers, timeout=10)
        info_data = info_resp.json()

        if info_data.get("code") == 0:
            node = info_data.get("data", {}).get("node", {})
            obj_type = node.get("obj_type", "")
            obj_token = node.get("obj_token", "")
            if obj_type == "docx" and obj_token:
                # wiki 节点实际是 docx，用 docx API 读取
                return read_feishu_doc_by_token(obj_token)

            # 尝试直接通过 wiki token 读取纯文本
            space_id = node.get("space_id", "")
            if space_id:
                # 获取文档纯文本
                raw_url = f"https://open.feishu.cn/open-apis/docx/v1/documents/{wiki_token}/raw_content"
                raw_resp = requests.get(raw_url, headers=headers, timeout=15)
                raw_data = raw_resp.json()
                if raw_data.get("code") == 0:
                    return raw_data.get("data", {}).get("content", "")
    except Exception:
        pass

    # 降级：直接用 docx API 尝试
    content = read_feishu_doc_by_token(wiki_token)
    if content:
        return content

    logger.warning(f"Wiki 文档读取失败: {wiki_token}")
    return ""


def import_feishu_docs(urls: list[str]) -> int:
    """批量导入飞书文档（支持 wiki/docx/folder URL 列表）"""
    from knowledge.sqlite_store import insert_item, _get_conn
    import uuid

    total = 0
    for url in urls:
        token_str, url_type = _extract_token_from_url(url.strip())
        if not token_str:
            logger.warning(f"无法解析 URL: {url}")
            continue

        if url_type == "folder":
            count = import_feishu_folder_to_sqlite(token_str)
            total += count
            continue

        if url_type == "bitable":
            # 多维表格：读取所有记录导入
            records = read_bitable_records()
            for rec in records:
                rid = rec.get("id", "")
                if not rid or not rec.get("full_content"):
                    continue
                conn = _get_conn()
                existing = conn.execute(
                    "SELECT id FROM knowledge_items WHERE id = ?", (rid,)
                ).fetchone()
                if existing:
                    continue
                title = rec.get("full_content", "")[:100].split("\n")[0][:80]
                item_id = rid
                record = {
                    "id": item_id, "title": title,
                    "summary": rec.get("full_content", "")[:500],
                    "full_content": rec.get("full_content", ""),
                    "category": rec.get("category", "未分类"),
                    "tags": [], "source_type": "feishu_bitable",
                    "source_path": f"bitable:{token_str}",
                    "created_at": rec.get("created_at", int(time.time() * 1000)),
                }
                if insert_item(record):
                    total += 1
            logger.info(f"Bitable 导入: {total} 条")
            continue

        # 单个文档
        conn = _get_conn()
        existing = conn.execute(
            "SELECT id FROM knowledge_items WHERE source_path LIKE ?",
            (f"%{token_str}%",)
        ).fetchone()
        if existing:
            logger.debug(f"已存在，跳过: {token_str[:20]}")
            continue

        # 读取内容
        if url_type == "wiki":
            content = read_feishu_wiki_content(token_str)
        else:
            content = read_feishu_doc_by_token(token_str)

        if not content:
            logger.warning(f"无法读取内容: {url}")
            continue

        # 构建条目
        title = content.strip().split("\n")[0][:100] or token_str[:20]
        item_id = str(uuid.uuid4())

        name_lower = title.lower()
        category = "其他"
        if any(k in name_lower for k in ["ai", "llm", "agent", "rag", "大模型", "prompt", "gpt", "claude"]):
            category = "科技与AI"
        elif any(k in name_lower for k in ["产品", "prd", "需求", "竞品", "原型"]):
            category = "产品与工具"
        elif any(k in name_lower for k in ["财务", "会计", "税务", "费控", "核算"]):
            category = "职场与创业"

        record = {
            "id": item_id, "title": title, "summary": content[:500],
            "full_content": content, "category": category, "tags": [],
            "source_type": f"feishu_{url_type}", "source_path": f"{url_type}:{token_str}",
            "created_at": int(time.time() * 1000),
        }
        if insert_item(record):
            total += 1
            logger.info(f"导入: {title[:50]}")

    return total


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
