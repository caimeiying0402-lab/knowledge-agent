#!/usr/bin/env bash
# Career Agent 定时包装 — 每小时尝试，每天只跑一次
# 前提: Mac 开机 + 隔离 Chrome 运行中(bash start_chrome_cdp.sh)
set -e
cd "$(dirname "$0")"

LOG="logs/career-agent.log"
STAMP_FILE="data/.career_last_run"
mkdir -p logs data/job_output

TODAY=$(date +%Y%m%d)

# 今天已经跑过了？
if [ -f "$STAMP_FILE" ] && [ "$(cat "$STAMP_FILE")" = "$TODAY" ]; then
    exit 0  # 静默跳过
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Career Agent 尝试执行..." >> "$LOG"

# Chrome CDP 在吗？
if ! curl -s http://localhost:9222/json/version > /dev/null 2>&1; then
    echo "[$(date)] ⚠️  Chrome CDP 不可用，跳过" >> "$LOG"
    exit 0
fi

echo "[$(date)] 开始岗位搜索..." >> "$LOG"

source .venv/bin/activate
export PYTHONPATH="$PWD/src"

# 运行并记录
python -m agents.career_agent --search-only --engine cdp --platform both --max-results 15 >> "$LOG" 2>&1 && \
    echo "$TODAY" > "$STAMP_FILE"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 完成" >> "$LOG"
