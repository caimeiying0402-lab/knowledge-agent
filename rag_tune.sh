#!/usr/bin/env bash
# ============================================================
# RAG 调优工具 — 查看分块效果、检索结果，调整参数
# ============================================================
# 用法:
#   bash rag_tune.sh chunk <文档名>     # 查看某篇文档的分块结果
#   bash rag_tune.sh search <查询>      # 测试检索，看返回哪些 chunk
#   bash rag_tune.sh compare <查询>     # 对比不同 chunk_size 的检索差异
#   bash rag_tune.sh list               # 列出所有可检索的文档
# ============================================================
set -e
cd "$(dirname "$0")"
source .venv/bin/activate
export PYTHONPATH="$PWD/src"

MODE="${1:-help}"
ARG="${2:-}"

case "$MODE" in
    chunk|chunks)
        .venv/bin/python -c "
from skills.rag_tuner import show_chunks
show_chunks('$ARG')
"
        ;;
    search|s)
        .venv/bin/python -c "
from skills.rag_tuner import test_search
test_search('$ARG')
"
        ;;
    compare|cmp)
        .venv/bin/python -c "
from skills.rag_tuner import compare_chunk_sizes
compare_chunk_sizes('$ARG')
"
        ;;
    list|ls)
        .venv/bin/python -c "
from skills.rag_tuner import list_documents
list_documents()
"
        ;;
    profile)
        .venv/bin/python -c "
from skills.rag_tuner import show_profile_context
show_profile_context()
"
        ;;
    *)
        echo "RAG 调优工具"
        echo ""
        echo "用法: bash rag_tune.sh <命令> [参数]"
        echo ""
        echo "命令:"
        echo "  list                  列出所有可检索的文档"
        echo "  chunk <文档名>         查看分块结果（每个chunk的内容和边界）"
        echo "  search <查询文本>      测试检索，看 RAG 返回哪些 chunk"
        echo "  compare <查询文本>     对比不同 chunk_size(200/500/1000) 的检索差异"
        echo "  profile                查看当前用户画像（RAG 检索用的 query）"
        echo ""
        echo "示例:"
        echo "  bash rag_tune.sh list"
        echo "  bash rag_tune.sh chunk AI学习"
        echo "  bash rag_tune.sh search 财务系统架构设计"
        echo "  bash rag_tune.sh compare 月结流程"
        ;;
esac
