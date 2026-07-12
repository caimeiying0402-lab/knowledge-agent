#!/usr/bin/env bash
# ============================================================
# 飞书文档导入 — 支持 Wiki / Doc / Folder URL
# ============================================================
# 用法:
#   bash feishu_import.sh <URL>
#   bash feishu_import.sh <URL1> <URL2> <URL3> ...
#
# 支持的 URL 格式:
#   飞书 Wiki:  https://my.feishu.cn/wiki/HBapwWqmZiQPvkkTr4kci6fKnse
#   飞书文档:  https://xxx.feishu.cn/docx/xxxxx
#   飞书文件夹: https://xxx.feishu.cn/drive/folder/fldcnXXXXX
# ============================================================
set -e
cd "$(dirname "$0")"
source .venv/bin/activate
export PYTHONPATH="$PWD/src"

if [ $# -eq 0 ]; then
    echo "用法: bash feishu_import.sh <飞书URL> [URL2] [URL3] ..."
    echo ""
    echo "示例:"
    echo "  bash feishu_import.sh https://my.feishu.cn/wiki/HBapwWqmZiQPvkkTr4kci6fKnse"
    echo "  bash feishu_import.sh https://xxx.feishu.cn/drive/folder/fldcnXXXXX"
    echo ""
    echo "支持多个 URL，空格分隔"
    exit 1
fi

echo "📂 正在导入飞书文档..."
echo ""

# 将参数拼接为 Python list
URLS_JSON=$(printf '"%s",' "$@")
URLS_JSON="[${URLS_JSON%,}]"

.venv/bin/python -c "
import json
from skills.feishu_skill import import_feishu_docs, _extract_token_from_url

urls = json.loads('''$URLS_JSON''')
print(f'共 {len(urls)} 个文档/文件夹')
print()

count = import_feishu_docs(urls)
print()
print(f'✅ 导入完成: {count} 条新增')

from knowledge.sqlite_store import get_stats
stats = get_stats()
print(f'知识库总计: {stats[\"total\"]} 条')
"

echo ""
echo "💡 导入后建议: bash profile.sh gen   # 重新生成兴趣画像"
