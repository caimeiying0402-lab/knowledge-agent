import os
import requests
from dotenv import load_dotenv
from pathlib import Path

# 获取项目根目录并加载 .env 文件
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
        record (dict): 包含字段键值对的字典。日期字段 'created_at' 的值必须是毫秒级时间戳。
    """
    token = get_tenant_access_token()
    app_token = os.getenv("FEISHU_APP_TOKEN")
    table_id = os.getenv("FEISHU_TABLE_ID")
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # ✅ 关键修改点：将日期字段的值，由外部传入的字符串改为时间戳数字
    # 确保 main.py 中调用时，传入的 'created_at' 值是时间戳
    payload = {
        "fields": {
            "id": record.get("id", ""),
            "source_type": record.get("source_type", ""),
            "source_path": record.get("source_path", ""),
            "title": record.get("title", ""),
            "summary": record.get("summary", ""),
            "full_content": record.get("full_content", ""),
            "tags": record.get("tags", []),   # 直接传递列表
            "category": record.get("category", ""),
            "embedding_status": record.get("embedding_status", False),
            # ✅ 这里的 "created_at" 必须对应飞书表格中的日期字段列名
            "created_at": record.get("created_at", 0)
        }
    }
    
    res = requests.post(url, headers=headers, json=payload)
    return res.json()