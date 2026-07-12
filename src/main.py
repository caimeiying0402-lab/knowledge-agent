"""Knowledge Agent 主流程 v5：ingest → summarize → structured_format → feishu + sqlite + chroma
v5: 结构化格式化 skill 接入，飞书展示改为用户偏好的编号层级风格
"""
import uuid
import logging
import threading
from datetime import datetime
from skills.ingestion_skill import ingest
from skills.summary_skill import summarize
from skills.structured_format_skill import format_structured
from skills.feishu_skill import write_to_bitable

logger = logging.getLogger(__name__)

# ── 平台可视化标签 ──
PLATFORM_LABELS = {
    "xiaohongshu": "📕 小红书", "douban": "📗 豆瓣", "wechat_mp": "📰 公众号",
    "zhihu": "🧠 知乎", "baike_baidu": "📚 百度百科", "sspai": "🔧 少数派",
    "wikipedia": "🌐 Wikipedia", "generic": "🌍 网页", "text": "📝 文本", "file": "📎 文件",
}


def process(source: str) -> dict:
    """
    完整 ETL 管道（v4）：
    1. 采集（URL/文件/文本）
    2. DeepSeek 结构化摘要（含平台上下文）
    3. 写入飞书多维表格
    4. 同步写入 SQLite 本地库
    5. 异步 Embedding → Chroma 入库（支持百炼 API 或 ONNX 自动）
    """
    # ── 1. 采集 ──
    ingested = ingest(source)
    raw_content = ingested.get("raw_content", "")
    platform = ingested.get("platform", "unknown")
    source_url = ingested.get("source_url", "") or ingested.get("source_path", "")

    # ── 2. 结构化摘要（传递平台上下文）──
    summary_result = summarize(raw_content, platform=platform)

    # ── 2.5 结构化格式化：转为编号层级笔记 ──
    structured_note = format_structured(
        title=summary_result.get("title", ""),
        summary=summary_result.get("summary", ""),
        highlights=summary_result.get("highlights", []),
        raw_content=raw_content,
        tags=summary_result.get("tags", []),
    )

    # ── 3. full_content：结构化笔记为主，原文为辅 ──
    full_content = structured_note if structured_note else _smart_truncate(raw_content)

    # ── 4. 构建完整记录 ──
    # 注意：调试用字段（source_path/id/tags等）仍保留在 SQLite/日志，
    # 飞书仅展示 title + full_content(结构化笔记) + category
    record = {
        "id": str(uuid.uuid4()),
        "source_type": platform,
        "source_path": source_url,
        "title": summary_result.get("title", ""),
        "summary": summary_result.get("summary", ""),  # 飞书中隐藏，仅供调试
        "full_content": full_content,
        "raw_content": raw_content,  # 保留原始文本，用于回顾展示
        "highlights": summary_result.get("highlights", []),  # 已内嵌到 structured_note
        "tags": summary_result.get("tags", []),
        "category": summary_result.get("category", ""),
        "source_quality": summary_result.get("source_quality", ""),
        "actionable": summary_result.get("actionable", None),
        "created_at": int(datetime.now().timestamp() * 1000),
        "embedding_status": False,
    }

    # ── 5. 写入飞书 + Obsidian vault ──
    result = write_to_bitable(record)
    if result.get("code") == 0:
        record["record_id"] = result["data"]["record"]["record_id"]
        _print_success(record, platform)
    else:
        print(f"❌ 飞书写入失败: {result}")

    # Obsidian vault 写入（后台，不影响主流程）
    try:
        from skills.obsidian_skill import write_to_vault
        write_to_vault(record)
    except Exception:
        pass

    # ── 6. 同步写入 SQLite ──
    _save_to_sqlite(record)

    # ── 7. 异步 Embedding + Chroma 入库 ──
    threading.Thread(
        target=_embed_async,
        args=(record,),
        daemon=True,
    ).start()

    return record


def _smart_truncate(content: str, max_chars: int = 5000) -> str:
    """智能截断：在最近句号处断开，避免截断在词中"""
    if len(content) <= max_chars:
        return content

    truncated = content[:max_chars]
    last_period = max(
        truncated.rfind("。", max_chars - 200),
        truncated.rfind("！", max_chars - 200),
        truncated.rfind("？", max_chars - 200),
        truncated.rfind("\n", max_chars - 200),
    )
    if last_period > max_chars // 2:
        return truncated[:last_period + 1] + "\n\n…(内容过长已截断)"
    return truncated + "\n\n…(内容过长已截断)"


def _save_to_sqlite(record: dict):
    """同步写入 SQLite，失败不影响主流程"""
    try:
        from skills.sqlite_skill import save_to_sqlite
        if save_to_sqlite(record):
            print(f"  📥 SQLite: 已同步入库")
        else:
            print(f"  ⚠️ SQLite: 写入跳过（可能已存在）")
    except Exception as e:
        logger.warning(f"SQLite 写入失败（不影响主流程）: {e}")


def _embed_async(record: dict):
    """后台异步生成 Embedding 并存入 Chroma"""
    try:
        from skills.embedding_skill import embed_record, get_embedding_method
        from knowledge.chroma_store import add_to_chroma

        # 尝试外部 Embedding（百炼 API 优先，ONNX 备选）
        embedding = embed_record(record)
        method_name = get_embedding_method()

        # 写入 Chroma：有外部 embedding 就用，没有也让 ChromaDB 自动 embedding
        if add_to_chroma(record, embedding):
            # 标记 SQLite 中该记录已完成向量化
            try:
                from knowledge.sqlite_store import mark_embedded
                mark_embedded(record["id"])
            except Exception:
                pass
            if embedding is not None:
                print(f"  🧬 Chroma: 向量化完成 ({method_name}, 维度={len(embedding)})")
            else:
                print(f"  🧬 Chroma: 自动向量化完成 (ChromaDB ONNX)")
        else:
            logger.debug(f"Chroma 写入失败: {record['id'][:8]}")
    except Exception as e:
        logger.warning(f"Async Embedding 失败: {e}")


def _print_success(record: dict, platform: str):
    """可视化输出入库结果"""
    title = record.get("title", "")[:40]
    category = record.get("category", "")
    platform_label = PLATFORM_LABELS.get(platform, f"📌 {platform}")
    structured = record.get("full_content", "")

    print(f"✅ 入库成功: {title}")
    print(f"   来源: {platform_label} | 分类: {category}")
    if structured:
        # 显示结构化笔记的前几行作为预览
        lines = structured.strip().split("\n")
        preview_lines = [l for l in lines[:8] if l.strip()]
        for l in preview_lines:
            print(f"   {l}")


if __name__ == "__main__":
    print("=" * 60)
    print("  Knowledge Agent v4 — SQLite + Chroma + RAG")
    print("  macOS x86_64 兼容版（百炼/ONNX Embedding）")
    print("=" * 60)

    # 测试1：纯文本
    print("\n[1/4] 纯文本测试...")
    process("今天学习了马斯洛需求层次理论，人的需求从底层到高层分为："
            "生理需求、安全需求、社交需求、尊重需求、自我实现。"
            "这让我重新思考了职业规划——原来我一直卡在安全需求层，"
            "应该先解决经济基础再追求自我实现。")

    # 测试2：通用 URL
    print("\n[2/4] URL 测试...")
    process("https://sspai.com/post/70486")

    # 测试3：技术类文本
    print("\n[3/4] 技术内容测试...")
    process("Claude Code 是 Anthropic 推出的 AI 编程助手，它可以直接在你的终端中运行。"
            "与传统的 IDE 插件不同，Claude Code 是一个命令行工具，"
            "它能够理解整个代码库的上下文，支持多文件编辑、Git 操作、"
            "运行测试和调试。安装方法：npm install -g @anthropic-ai/claude-code")

    # 测试4：SQLite + Chroma + RAG 检索验证
    print("\n[4/4] 知识库检索验证...")
    import time
    time.sleep(3)  # 等异步 embedding 完成

    # Chroma 统计
    from knowledge.chroma_store import get_chroma_stats
    chroma_stats = get_chroma_stats()
    print(f"  📊 ChromaDB: {chroma_stats}")

    # RAG 语义搜索
    print("  🔍 语义搜索: '编程工具'")
    from knowledge.rag_retriever import search
    results = search("编程工具", top_k=3)
    for r in results:
        method = r.get("search_method", "unknown")
        print(f"    [{method}] {r.get('title', '')[:40]} (score={r.get('similarity_score', 'N/A')})")

    # SQLite 统计
    print("\n  📊 SQLite 统计:")
    from skills.sqlite_skill import get_knowledge_stats
    stats = get_knowledge_stats()
    print(f"    总条目: {stats.get('total', 0)} | 已向量化: {stats.get('embedded', 0)}")
