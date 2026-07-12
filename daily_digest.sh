#!/usr/bin/env bash
# 每日汇总推送 — 先同步飞书文档 + 合并知识库回顾 + 网络发现，一条微信消息
set -e
cd "$(dirname "$0")"
source .venv/bin/activate
export PYTHONPATH="$PWD/src"

# Step 0: 同步飞书文档（确保回顾基于最新内容）
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 📡 飞书同步检查..." >> logs/daily_digest.log
.venv/bin/python -c "
from skills.feishu_skill import sync_feishu_sources
stats = sync_feishu_sources()
if stats['new'] + stats['updated'] > 0:
    print(f'[SYNC] 新增{stats[\"new\"]} 更新{stats[\"updated\"]}')
" >> logs/daily_digest.log 2>&1 || true

# Step 1: 发送每日精选
.venv/bin/python -c "from skills.daily_digest_skill import send_daily_digest; send_daily_digest()" >> logs/daily_digest.log 2>&1
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 每日汇总推送完成" >> logs/daily_digest.log
