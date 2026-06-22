import sqlite3
import os
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional

# ============================================================
# 第一部分：数据库路径发现（Mac 微信）
# ============================================================

def find_wechat_databases() -> List[Path]:
    """
    查找 Mac 微信的所有聊天数据库路径
    返回: [Path('/path/to/msg.db'), ...]
    """
    home = Path.home()
    
    # Mac 微信数据库基础路径
    base_path = home / "Library/Containers/com.tencent.xinWeChat/Data/Library/Application Support/com.tencent.xinWeChat"
    
    if not base_path.exists():
        print(f"[错误] 微信数据库目录不存在: {base_path}")
        print("请确认：1) 微信已登录 2) 微信版本支持")
        return []
    
    db_files = []
    # 遍历找到所有 msg.db
    for root, dirs, files in os.walk(base_path):
        if "msg.db" in files:
            db_path = Path(root) / "msg.db"
            db_files.append(db_path)
            print(f"[发现] {db_path}")
    
    return db_files


def get_filehelper_chat_id(db_path: Path) -> Optional[str]:
    """
    获取文件传输助手的会话 ID
    微信中文件传输助手的用户名通常是 'filehelper'
    """
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    try:
        # 方法1：通过 username 查找
        cursor.execute("""
            SELECT username, chat_id FROM ChatInfo 
            WHERE username LIKE '%filehelper%' OR username = 'filehelper'
        """)
        result = cursor.fetchone()
        
        if result:
            conn.close()
            return result[1]  # chat_id
        
        # 方法2：通过 name 查找
        cursor.execute("""
            SELECT name, chat_id FROM ChatInfo 
            WHERE name LIKE '%文件传输%' OR name LIKE '%File Helper%'
        """)
        result = cursor.fetchone()
        
        conn.close()
        if result:
            return result[1]
            
    except sqlite3.Error as e:
        print(f"[错误] 查询失败: {e}")
    
    conn.close()
    return None


def get_table_info(db_path: Path, table_name: str) -> List[str]:
    """
    获取表的列结构（用于逆向分析）
    """
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [col[1] for col in cursor.fetchall()]
    
    conn.close()
    return columns


def get_recent_messages(
    db_path: Path, 
    chat_id: str, 
    hours_back: int = 24,
    limit: int = 50
) -> List[Dict]:
    """
    获取某个会话的最近消息
    
    Args:
        db_path: 数据库路径
        chat_id: 会话ID
        hours_back: 回溯小时数
        limit: 最大消息数
    
    Returns:
        [{"content": "消息内容", "timestamp": 时间戳, "type": 消息类型}, ...]
    """
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # 计算时间阈值（毫秒时间戳）
    time_threshold = int((datetime.now() - timedelta(hours=hours_back)).timestamp() * 1000)
    
    try:
        # 尝试多种可能的字段名（微信版本不同有差异）
        # 常见表名: Message, message, MSG
        possible_tables = ["Message", "message", "MSG"]
        possible_content_fields = ["message_content", "content", "message", "text"]
        possible_time_fields = ["create_time", "time", "msg_time", "timestamp"]
        
        messages = []
        
        for table in possible_tables:
            for content_field in possible_content_fields:
                for time_field in possible_time_fields:
                    try:
                        cursor.execute(f"""
                            SELECT {content_field}, {time_field}, message_type 
                            FROM {table} 
                            WHERE chat_id = ? AND {time_field} > ?
                            ORDER BY {time_field} DESC
                            LIMIT ?
                        """, (chat_id, time_threshold, limit))
                        
                        rows = cursor.fetchall()
                        if rows:
                            for row in rows:
                                content = row[0] if row[0] else ""
                                messages.append({
                                    "content": str(content),
                                    "timestamp": row[1],
                                    "type": row[2] if len(row) > 2 else 0
                                })
                            conn.close()
                            return messages
                    except sqlite3.Error:
                        continue
        
        # 如果都失败，尝试直接查所有列
        cursor.execute(f"SELECT * FROM Message LIMIT 1")
        columns = [description[0] for description in cursor.description]
        print(f"[调试] Message 表的列: {columns}")
        
    except sqlite3.Error as e:
        print(f"[错误] 查询消息失败: {e}")
    
    conn.close()
    return []


# ============================================================
# 第四部分：统一入口函数
# ============================================================

def collect_from_filehelper(hours_back: int = 24) -> List[Dict]:
    """
    从文件传输助手采集消息（主入口函数）
    
    Args:
        hours_back: 采集最近多少小时的消息
    
    Returns:
        消息列表，每条包含 content, timestamp, type
    """
    db_paths = find_wechat_databases()
    
    if not db_paths:
        print("[错误] 未找到微信数据库")
        print("请确认：")
        print("1. 微信已登录并同步了消息")
        print("2. 曾使用过文件传输助手")
        return []
    
    for db_path in db_paths:
        print(f"[检查] {db_path}")
        
        # 获取文件传输助手的 chat_id
        chat_id = get_filehelper_chat_id(db_path)
        
        if chat_id:
            print(f"[成功] 找到文件传输助手，chat_id: {chat_id}")
            
            # 获取消息
            messages = get_recent_messages(db_path, chat_id, hours_back)
            
            if messages:
                print(f"[成功] 获取到 {len(messages)} 条消息")
                return messages
            else:
                print("[提示] 该数据库中没有找到文件传输助手的消息")
        else:
            print("[提示] 未找到文件传输助手会话")
    
    return []


# ============================================================
# 第五部分：调试和测试函数
# ============================================================

def explore_database(db_path: Path):
    """
    探索数据库结构（逆向分析用）
    打印所有表名和列名
    """
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # 获取所有表
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    
    print(f"\n=== 数据库: {db_path} ===")
    print(f"共 {len(tables)} 个表\n")
    
    for table in tables:
        table_name = table[0]
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        
        print(f"表: {table_name}")
        print(f"  列数: {len(columns)}")
        for col in columns[:5]:  # 只显示前5列
            print(f"    - {col[1]} ({col[2]})")
        if len(columns) > 5:
            print(f"    ... 还有 {len(columns)-5} 列")
        print()
    
    conn.close()


def test():
    """测试函数"""
    print("=" * 50)
    print("微信数据库采集测试")
    print("=" * 50)
    
    # 1. 查找数据库
    db_paths = find_wechat_databases()
    
    if not db_paths:
        print("\n❌ 未找到微信数据库")
        return
    
    # 2. 探索第一个数据库的结构
    print("\n📁 探索数据库结构...")
    explore_database(db_paths[0])
    
    # 3. 尝试采集消息
    print("\n📨 尝试从文件传输助手采集消息...")
    messages = collect_from_filehelper(hours_back=168)  # 最近一周
    
    if messages:
        print(f"\n✅ 采集到 {len(messages)} 条消息:")
        for i, msg in enumerate(messages[:5]):  # 只显示前5条
            print(f"\n[{i+1}] {msg['content'][:100]}...")
            print(f"    时间戳: {msg['timestamp']}")
    else:
        print("\n⚠️ 未采集到消息")
        print("可能原因:")
        print("1. 文件传输助手中没有消息")
        print("2. 微信数据库版本不同，表结构有差异")
        print("3. 需要先手动发送一条消息到文件传输助手")


if __name__ == "__main__":
    test()