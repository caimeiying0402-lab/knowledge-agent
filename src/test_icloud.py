"""
测试脚本：向 KnowledgeAgentInbox 写入测试文件，验证 icloud_skill.py 能正确触发处理。
用法：python src/test_icloud.py
"""

import json
from pathlib import Path

INBOX = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/KnowledgeAgentInbox"
TEST_FILE = INBOX / "test_20240101_text.json"

payload = {"type": "text", "content": "测试文本，确认 icloud_skill 链路正常"}

INBOX.mkdir(parents=True, exist_ok=True)
TEST_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

print(f"测试文件已写入：{TEST_FILE}")
print("请观察 icloud_skill.py 是否触发处理")
