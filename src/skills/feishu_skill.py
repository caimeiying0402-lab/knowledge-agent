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


def read_bitable_records(app_token: str = None, table_id: str = None,
                         page_size: int = 100) -> list[dict]:
    """从飞书多维表格读取所有记录。
    app_token/table_id 可选，不传则从环境变量读取（知识库主表）。
    """
    token = get_tenant_access_token()
    app_token = app_token or os.getenv("FEISHU_APP_TOKEN")
    table_id = table_id or os.getenv("FEISHU_TABLE_ID")
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
            "raw_content": content,  # 飞书文档内容是原文
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


def _extract_token_from_url(url: str) -> dict:
    """从飞书 URL 提取 {token, type, table_id?}
    支持: /wiki/xxx, /docx/xxx, /docs/xxx, /drive/folder/xxx, /base/xxx?table=yyy
    """
    import re
    from urllib.parse import urlparse, parse_qs

    result = {"token": "", "type": "", "table_id": None}

    # wiki 文档: https://my.feishu.cn/wiki/HBapwWqmZiQPvkkTr4kci6fKnse
    m = re.search(r'/wiki/([A-Za-z0-9_-]{10,})', url)
    if m:
        result["token"] = m.group(1)
        result["type"] = "wiki"
        return result
    # docx 文档
    m = re.search(r'/docx/([A-Za-z0-9_-]{10,})', url)
    if m:
        result["token"] = m.group(1)
        result["type"] = "docx"
        return result
    # docs 文档
    m = re.search(r'/docs/([A-Za-z0-9_-]{10,})', url)
    if m:
        result["token"] = m.group(1)
        result["type"] = "doc"
        return result
    # drive folder
    m = re.search(r'/folder/([A-Za-z0-9_-]{10,})', url)
    if m:
        result["token"] = m.group(1)
        result["type"] = "folder"
        return result
    # bitable/base: https://my.feishu.cn/base/PppsbADLlaneZVs6tUrcPfg2nef?table=tblXkujE0Ea4mAih
    m = re.search(r'/base/([A-Za-z0-9_-]{10,})', url)
    if m:
        result["token"] = m.group(1)
        result["type"] = "bitable"
        # 提取 query 参数中的 table_id
        try:
            qs = parse_qs(urlparse(url).query)
            result["table_id"] = qs.get("table", [None])[0]
        except Exception:
            pass
        return result
    # 纯 token
    if re.match(r'^[A-Za-z0-9_-]{10,}$', url.strip()):
        result["token"] = url.strip()
        result["type"] = "unknown"
        return result
    return result


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
        info = _extract_token_from_url(url.strip())
        token_str = info["token"]
        url_type = info["type"]
        if not token_str:
            logger.warning(f"无法解析 URL: {url}")
            continue

        if url_type == "folder":
            count = import_feishu_folder_to_sqlite(token_str)
            total += count
            continue

        if url_type == "bitable":
            # 多维表格：读取所有记录导入（支持指定 table_id）
            records = read_bitable_records(
                app_token=token_str,
                table_id=info.get("table_id"),
            )
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
                    "raw_content": rec.get("full_content", ""),  # bitable内容即原文
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
            "full_content": content, "raw_content": content,
            "category": category, "tags": [],
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
            "raw_content": rec.get("full_content", ""),
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


# ── 自动同步 ──

def _compute_content_hash(content: str) -> str:
    """计算内容的简短哈希，用于检测内容变化"""
    import hashlib
    return hashlib.md5(content.encode("utf-8")).hexdigest()[:16]


def _classify_content(title: str, content: str) -> str:
    """根据标题和内容自动分类"""
    text = f"{title} {content[:500]}".lower()
    if any(k in text for k in ["ai", "llm", "agent", "rag", "大模型", "prompt", "gpt", "claude", "deepseek", "神经网络"]):
        return "科技与AI"
    if any(k in text for k in ["产品", "prd", "需求", "竞品", "原型", "用户体验", "交互"]):
        return "产品与工具"
    if any(k in text for k in ["财务", "会计", "税务", "费控", "核算", "sap", "fico"]):
        return "职场与创业"
    if any(k in text for k in ["面试", "简历", "求职", "职业", "跳槽"]):
        return "职场与创业"
    if any(k in text for k in ["效率", "工具", "方法", "习惯", "工作流", "自动化"]):
        return "效率方法"
    if any(k in text for k in ["抖音", "短视频", "内容运营", "直播", "电商"]):
        return "产品与工具"
    if any(k in text for k in ["读书", "阅读", "电影", "音乐", "书单"]):
        return "阅读与影视"
    if any(k in text for k in ["投资", "理财", "股票", "基金", "商业"]):
        return "投资与商业"
    return "其他"


def sync_feishu_sources(config_path: str = None) -> dict:
    """
    自动同步配置的飞书文档源。
    检查每个 URL，内容变化时自动更新本地知识库。

    Returns:
        {"new": 新增数, "updated": 更新数, "unchanged": 未变数, "errors": 错误数}
    """
    import yaml
    from knowledge.sqlite_store import upsert_item, get_item_by_source_path
    import uuid

    if config_path is None:
        config_path = str(base_dir / "config" / "feishu_sources.yaml")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.warning(f"飞书同步配置不存在: {config_path}")
        return {"new": 0, "updated": 0, "unchanged": 0, "errors": 0}

    sources = config.get("sources", [])
    if not sources:
        logger.info("没有配置飞书同步源")
        return {"new": 0, "updated": 0, "unchanged": 0, "errors": 0}

    stats = {"new": 0, "updated": 0, "unchanged": 0, "errors": 0}
    now_ms = int(time.time() * 1000)

    for src in sources:
        url = src.get("url", "").strip()
        if not url:
            continue
        override_category = src.get("category")

        try:
            info = _extract_token_from_url(url)
            token_str = info["token"]
            url_type = info["type"]
            table_id = info.get("table_id")
            if not token_str:
                logger.warning(f"无法解析 URL: {url}")
                stats["errors"] += 1
                continue

            # 读取飞书内容
            if url_type == "bitable":
                # 多维表格：读取指定 base/table 的所有记录
                records = read_bitable_records(
                    app_token=token_str,
                    table_id=table_id,
                )
                for rec in records:
                    rid = rec.get("id", "")
                    content = rec.get("full_content", "")
                    if not rid or not content:
                        continue

                    content_hash = _compute_content_hash(content)
                    existing = get_item_by_source_path(rid)
                    if existing and existing.get("raw_content"):
                        old_hash = _compute_content_hash(existing.get("raw_content", ""))
                        if old_hash == content_hash:
                            stats["unchanged"] += 1
                            continue

                    # 构建/更新记录
                    title = content[:100].split("\n")[0][:80]
                    cat = override_category or rec.get("category") or _classify_content(title, content)
                    record = {
                        "id": rid, "title": title,
                        "summary": content[:500],
                        "full_content": content,
                        "raw_content": content,
                        "category": cat, "tags": [],
                        "source_type": "feishu_bitable",
                        "source_path": f"bitable:{token_str}",
                        "created_at": rec.get("created_at", now_ms),
                    }
                    if upsert_item(record):
                        if existing:
                            stats["updated"] += 1
                        else:
                            stats["new"] += 1

            elif url_type == "folder":
                count = import_feishu_folder_to_sqlite(token_str)
                stats["new"] += count

            else:
                # 单个文档 (wiki/docx/doc)
                if url_type == "wiki":
                    content = read_feishu_wiki_content(token_str)
                else:
                    content = read_feishu_doc_by_token(token_str)

                if not content:
                    logger.warning(f"无法读取内容: {url}")
                    stats["errors"] += 1
                    continue

                content_hash = _compute_content_hash(content)
                source_path = f"{url_type}:{token_str}"
                existing = get_item_by_source_path(token_str)

                if existing and existing.get("raw_content"):
                    old_hash = _compute_content_hash(existing.get("raw_content", ""))
                    if old_hash == content_hash:
                        stats["unchanged"] += 1
                        continue

                # 构建记录
                title = content.strip().split("\n")[0][:100] or token_str[:20]
                cat = override_category or _classify_content(title, content)
                record_id = existing["id"] if existing else str(uuid.uuid4())

                record = {
                    "id": record_id, "title": title,
                    "summary": content[:500],
                    "full_content": content,
                    "raw_content": content,
                    "category": cat, "tags": [],
                    "source_type": f"feishu_{url_type}",
                    "source_path": source_path,
                    "created_at": existing["created_at"] if existing else now_ms,
                }

                if upsert_item(record):
                    if existing:
                        stats["updated"] += 1
                        logger.info(f"飞书更新: {title[:50]}")
                    else:
                        stats["new"] += 1
                        logger.info(f"飞书新增: {title[:50]}")

        except Exception as e:
            logger.warning(f"同步失败 [{url[:50]}]: {e}")
            stats["errors"] += 1

    logger.info(
        f"飞书同步完成: 新增{stats['new']} "
        f"更新{stats['updated']} "
        f"未变{stats['unchanged']} "
        f"错误{stats['errors']}"
    )
    return stats
