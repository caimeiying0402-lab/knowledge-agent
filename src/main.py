"""Knowledge Agent 主流程：ingest → summarize → feishu"""
import uuid
from datetime import datetime
from skills.ingestion_skill import ingest
from skills.summary_skill import summarize
from skills.feishu_skill import write_to_bitable


def process(source: str) -> dict:
    """
    完整 ETL 管道：
    1. 采集（URL/文件/文本）
    2. DeepSeek 摘要
    3. 写入飞书多维表格
    """
    # ── 1. 采集 ──
    ingested = ingest(source)
    raw_content = ingested.get("raw_content", "")
    platform = ingested.get("platform", "unknown")
    source_url = ingested.get("source_url", "") or ingested.get("source_path", "")

    # ── 2. 摘要生成 ──
    summary_result = summarize(raw_content)

    # ── 3. 构建完整记录 ──
    # 飞书多维表格字段名（v2）：增加了 platform 和 source_url
    record = {
        "id": str(uuid.uuid4()),
        "source_type": platform,                    # 来源平台（xiaohongshu/douban/wechat_mp/...）
        "source_path": source_url,                  # 原始 URL 或文件路径
        "title": summary_result.get("title", ""),
        "summary": summary_result.get("summary", ""),
        "full_content": raw_content[:5000],          # 正文截断 5000 字符
        "tags": summary_result.get("tags", []),
        "category": summary_result.get("category", ""),
        "created_at": int(datetime.now().timestamp() * 1000),
        "embedding_status": False,
    }

    # ── 4. 写入飞书 ──
    result = write_to_bitable(record)
    if result.get("code") == 0:
        record["record_id"] = result["data"]["record"]["record_id"]
        print(f"✅ 入库成功: {record['title'][:30]} | record_id={record['record_id']}")
        # 显示来源信息
        label_map = {
            "xiaohongshu": "📕 小红书", "douban": "📗 豆瓣", "wechat_mp": "📰 公众号",
            "zhihu": "🧠 知乎", "baike_baidu": "📚 百度百科", "sspai": "🔧 少数派",
            "wikipedia": "🌐 Wikipedia", "generic": "🌍 网页", "text": "📝 文本", "file": "📎 文件",
        }
        label = label_map.get(platform, f"📌 {platform}")
        print(f"   来源: {label}")
        tags_str = "、".join(summary_result.get("tags", []))
        print(f"   分类: {summary_result.get('category', '')} | 标签: {tags_str}")
    else:
        print(f"❌ 飞书写入失败: {result}")

    return record


if __name__ == "__main__":
    # 快速测试
    print("=" * 60)
    print("  Knowledge Agent — 测试")
    print("=" * 60)

    # 测试文本
    print("\n[1/3] 纯文本测试...")
    process("今天学习了马斯洛需求层次理论，人的需求从底层到高层分为：生理需求、"
            "安全需求、社交需求、尊重需求、自我实现。这让我重新思考了职业规划。")

    # 测试通用 URL
    print("\n[2/3] URL 测试...")
    process("https://sspai.com/post/70486")
