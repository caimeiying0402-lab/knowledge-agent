#!/usr/bin/env bash
# 定时 Career Agent 包装脚本 — 确保 Chrome CDP 可用后运行
set -e
cd "$(dirname "$0")"

LOG="logs/career-agent.log"
mkdir -p logs data/job_output

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Career Agent 定时任务启动" >> "$LOG"

# 检查 Chrome CDP 是否可达
if ! curl -s http://localhost:9222/json/version > /dev/null 2>&1; then
    echo "[$(date)] ⚠️  Chrome CDP 不可用，跳过本次执行" >> "$LOG"
    echo "  提示: 请先运行 bash start_chrome_cdp.sh 启动隔离 Chrome" >> "$LOG"
    exit 0
fi

# 运行
source .venv/bin/activate
export PYTHONPATH="$PWD/src"
python -m agents.career_agent --search-only --engine cdp --platform both --max-results 15 >> "$LOG" 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Career Agent 完成" >> "$LOG"
