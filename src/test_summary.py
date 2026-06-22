#!/usr/bin/env python
import sys
from pathlib import Path

# 添加 src 到 Python 路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from skills.summary_skill import summarize

# 测试纯文本
result = summarize('Python 3.12 新特性：增加了更友好的错误提示和性能优化。')
print("===== 返回结果 =====")
print(result)
print(f"\ntitle字段: {result.get('title')}")
print(f"category字段: {result.get('category')}")
print(f"tags字段: {result.get('tags')}")