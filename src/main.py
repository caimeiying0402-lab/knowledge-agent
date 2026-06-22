import uuid
from datetime import datetime
from skills.ingestion_skill import ingest
from skills.summary_skill import summarize
from skills.feishu_skill import write_to_bitable

# ... 导入其他模块
import uuid
from datetime import datetime  # 确保引入了 datetime
# ...

def process(source: str):
    # 1. 采集
    ingested = ingest(source)
    
    # 2. 摘要生成
    summary_result = summarize(ingested["raw_content"])
    
    # 3. 构建完整记录
    record = {
        "id": str(uuid.uuid4()),
        "source_type": ingested["type"],
        "source_path": ingested["source_path"],
        "title": summary_result.get("title", ""),
        "summary": summary_result.get("summary", ""),
        "full_content": ingested["raw_content"][:5000],
        "tags": summary_result.get("tags", []),
        "category": summary_result.get("category", ""),
        # ✅ 关键修改点：生成毫秒级时间戳，而不是 ISO 8601 字符串
        "created_at": int(datetime.now().timestamp() * 1000),
        "embedding_status": False
    }
    
    # 4. 写入飞书
    result = write_to_bitable(record)
    print(f"写入结果: {result}")
    # 把飞书返回的 record_id 也带上，方便追踪
    if result.get("code") == 0:
        record["record_id"] = result["data"]["record"]["record_id"]
    return record

if __name__ == "__main__":
    process("https://www.xiaohongshu.com/discovery/item/6a1aed210000000006022fa0?source=webshare&xhsshare=pc_web&xsec_token=AB3wdFW3cZRPskib1ophux_G6qs9MX35lR47O_0ZDRZRg=&xsec_source=pc_share")
    process("data/images/test.png")
    process("这是一段手动输入的测试文本")