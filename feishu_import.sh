#!/usr/bin/env bash
# ============================================================
# 飞书文档导入 — 将飞书文件夹内容导入知识库
# ============================================================
set -e
cd "$(dirname "$0")"
source .venv/bin/activate
export PYTHONPATH="$PWD/src"

FOLDER_TOKEN="$1"

if [ -z "$FOLDER_TOKEN" ]; then
    echo "用法: bash feishu_import.sh <飞书文件夹token>"
    echo ""
    echo "获取文件夹 token 的方法:"
    echo "  1. 浏览器打开飞书 → 进入你要导入的文件夹"
    echo "  2. 复制URL中 /folder/ 后面的那串字符"
    echo "  3. 例如: https://xxx.feishu.cn/drive/folder/fldcnXXXXX"
    echo "           token 就是 fldcnXXXXX"
    echo ""
    exit 1
fi

echo "📂 正在扫描飞书文件夹: $FOLDER_TOKEN"
echo ""

.venv/bin/python -c "
from skills.feishu_skill import list_feishu_folder, import_feishu_folder_to_sqlite

# 先列出文件
files = list_feishu_folder('$FOLDER_TOKEN')
print(f'文件夹包含 {len(files)} 个文件:')
for f in files:
    icon = '📄' if f['type'] == 'docx' else '📊' if f['type'] == 'bitable' else '📁'
    print(f'  {icon} [{f[\"type\"]}] {f[\"name\"][:60]}')

# 导入文档
print()
print('正在导入文档内容...')
count = import_feishu_folder_to_sqlite('$FOLDER_TOKEN')
print(f'✅ 导入完成: {count} 条新增')

# 检查知识库总数
from knowledge.sqlite_store import get_stats
stats = get_stats()
print(f'知识库总计: {stats[\"total\"]} 条')
"

echo ""
echo "💡 导入后建议运行: bash profile.sh gen   # 重新生成兴趣画像"
