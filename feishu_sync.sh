#!/usr/bin/env bash
# ============================================================
# 飞书文档自动同步 — 检查配置的文档/表格是否有更新
# ============================================================
# 用法:
#   bash feishu_sync.sh           # 同步一次
#   bash feishu_sync.sh --watch   # 持续监控（每3小时）
#
# Cron 示例（每3小时同步）:
#   0 */3 * * * cd /path/to/knowledge-agent && bash feishu_sync.sh >> logs/feishu_sync.log 2>&1
# ============================================================
set -e
cd "$(dirname "$0")"
source .venv/bin/activate
export PYTHONPATH="$PWD/src"

sync_once() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 🔄 飞书同步开始..."
    .venv/bin/python -c "
from skills.feishu_skill import sync_feishu_sources
stats = sync_feishu_sources()
print(f'  新增: {stats[\"new\"]}  更新: {stats[\"updated\"]}  未变: {stats[\"unchanged\"]}  错误: {stats[\"errors\"]}')
"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ 飞书同步完成"
    echo ""
}

if [ "$1" = "--watch" ]; then
    echo "📡 持续监控模式（每3小时检查一次）"
    while true; do
        sync_once
        sleep 10800  # 3小时
    done
else
    sync_once
fi
