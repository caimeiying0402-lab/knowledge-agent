#!/usr/bin/env bash
# ============================================================
# 兴趣画像管理 — 生成/查看/重新生成
# ============================================================
set -e
cd "$(dirname "$0")"
source .venv/bin/activate
export PYTHONPATH="$PWD/src"

MODE="${1:-view}"

case "$MODE" in
    gen|generate|regenerate)
        echo "🔄 正在重新生成兴趣画像..."
        .venv/bin/python -c "
from skills.keyword_profile_skill import regenerate
regenerate()
print('✅ 画像已重新生成')
print('编辑文件: data/interest_profile.json')
"
        ;;
    view|show)
        .venv/bin/python -c "
from skills.keyword_profile_skill import load_profile
import json
p = load_profile()
print(f'生成时间: {p[\"generated_at\"]}')
print(f'人工审阅: {p[\"last_curated_at\"] or \"未审阅\"}')
print(f'知识库: {p[\"knowledge_base_stats\"][\"total\"]} 条')
print()
print(f'📝 画像摘要: {p[\"summary\"]}')
print()
print('🔑 关键词:')
for kw in p.get('keywords', []):
    curated = '✏️' if kw.get('curated') else '🤖'
    w = kw.get('curated_weight') or kw.get('weight', 0)
    print(f'  {curated} [{w:.0%}] {kw[\"term\"]} ({kw[\"category\"]})')
print()
print('📐 RAG检索维度:')
for d in p.get('rag_dimensions', []):
    print(f'  [{d[\"weight\"]:.0%}] {d[\"name\"]}')
    print(f'    查询: {d[\"query\"][:80]}')
print()
print('🔍 搜索查询:')
for q in p.get('search_queries', []):
    print(f'  • {q}')
print()
print('编辑画像: vim data/interest_profile.json')
print('重新生成: bash profile.sh gen')
"
        ;;
    edit)
        ${EDITOR:-vim} data/interest_profile.json
        ;;
    *)
        echo "用法: bash profile.sh [view|gen|edit]"
        echo "  view  - 查看当前画像（默认）"
        echo "  gen   - 重新生成画像"
        echo "  edit  - 手动编辑画像"
        ;;
esac
