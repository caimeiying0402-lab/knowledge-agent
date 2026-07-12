#!/usr/bin/env bash
# 每日汇总推送 — 合并知识库回顾 + 网络发现，一条微信消息
set -e
cd "$(dirname "$0")"
source .venv/bin/activate
export PYTHONPATH="$PWD/src"
.venv/bin/python -c "from skills.daily_digest_skill import send_daily_digest; send_daily_digest()" >> logs/daily_digest.log 2>&1
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 每日汇总推送完成" >> logs/daily_digest.log
