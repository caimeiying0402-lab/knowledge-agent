#!/usr/bin/env python3
"""
ChromaDB 回填脚本 — 将已有 SQLite 知识库数据迁移到 Chroma 向量库

用法:
    PYTHONPATH=src python scripts/backfill_chroma.py

功能:
    1. 从 SQLite 读取所有未向量化的记录
    2. 为每条记录生成 Embedding（百炼 API / ONNX 自动）
    3. 写入 ChromaDB
    4. 标记 SQLite 中对应记录为已向量化
"""
import sys
import logging
import time

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def backfill(batch_size: int = 10):
    """从 SQLite 回填数据到 Chroma"""
    from knowledge.sqlite_store import get_unembedded_items, mark_embedded, init_db
    from knowledge.chroma_store import add_to_chroma, get_chroma_stats
    from skills.embedding_skill import embed_record, get_embedding_method

    # 初始化
    init_db()

    # 获取未向量化记录
    items = get_unembedded_items(limit=1000)
    if not items:
        print("✅ 没有需要回填的记录，所有数据已向量化")
        return

    print(f"📋 找到 {len(items)} 条未向量化记录")
    print(f"   当前 Embedding 方案: {get_embedding_method()}")

    # 统计
    success = 0
    failed = 0

    for i, item in enumerate(items, 1):
        record_id = item.get("id", "")
        title = item.get("title", "")[:40]
        print(f"  [{i}/{len(items)}] 处理: {title}...", end=" ", flush=True)

        try:
            # 尝试外部 Embedding
            embedding = embed_record(item)

            # 写入 Chroma（有外部 embedding 就用，没有让 Chroma 自动生成）
            if add_to_chroma(item, embedding):
                # 标记为已向量化
                mark_embedded(record_id)
                method = get_embedding_method()
                dim = len(embedding) if embedding else "auto"
                print(f"✅ ({method}, dim={dim})")
                success += 1
            else:
                print("❌ Chroma 写入失败")
                failed += 1
        except Exception as e:
            print(f"❌ {e}")
            failed += 1

        # 避免频繁请求 API
        if embedding is not None and i % batch_size == 0:
            time.sleep(1)

    # 最终统计
    stats = get_chroma_stats()
    print(f"\n{'=' * 50}")
    print(f"回填完成: 成功 {success}, 失败 {failed}")
    print(f"ChromaDB: {stats}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    print("=" * 50)
    print("  ChromaDB 回填脚本")
    print("=" * 50)
    backfill()
