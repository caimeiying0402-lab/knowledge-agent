#!/usr/bin/env bash
# 每日汇总推送 — 先同步飞书文档 + 合并知识库回顾 + 网络发现，一条微信消息
set -e
cd "$(dirname "$0")"
source .venv/bin/activate
export PYTHONPATH="$PWD/src"

# 加载环境变量（SMTP、飞书等）
set -a
source config/.env
set +a

LOG_FILE="logs/daily_digest.log"
FAILURE_TRACKER="data/.digest_failure_count"

# ── 工具函数 ──

notify_desktop() {
    local title="$1"
    local msg="$2"
    osascript -e "display notification \"$msg\" with title \"$title\" sound name \"default\"" 2>/dev/null || true
}

# 检查网络连通性（DNS 是否正常）
check_network() {
    local host="$1"
    if command -v dscacheutil >/dev/null 2>&1; then
        dscacheutil -q host -a name "$host" >/dev/null 2>&1
    elif command -v nslookup >/dev/null 2>&1; then
        nslookup "$host" >/dev/null 2>&1
    else
        ping -c 1 -W 3 "$host" >/dev/null 2>&1
    fi
}

# 等待网络恢复（最多重试 3 次，间隔 30 秒）
wait_for_network() {
    local host="$1"
    local retries=3
    local i=0
    while [ $i -lt $retries ]; do
        if check_network "$host"; then
            return 0
        fi
        i=$((i + 1))
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠️ DNS 不通 ($host)，${i}/${retries} 秒后重试..." >> "$LOG_FILE"
        sleep 30
    done
    return 1
}

# 连续失败计数器
record_failure() {
    local count=0
    if [ -f "$FAILURE_TRACKER" ]; then
        count=$(cat "$FAILURE_TRACKER" | tr -d '[:space:]')
        count=$((count + 1))
    else
        count=1
    fi
    echo "$count" > "$FAILURE_TRACKER"
    if [ "$count" -ge 3 ]; then
        notify_desktop "AIOS 推送告警" "连续 ${count} 天推送失败，请检查网络和授权码"
    fi
}

clear_failure() {
    rm -f "$FAILURE_TRACKER"
}

# ── 主流程 ──

main() {
    local feishu_ok=false
    local push_ok=false

    # Step 0: 同步飞书文档（带网络重试）
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 📡 飞书同步检查..." >> "$LOG_FILE"

    if wait_for_network "open.feishu.cn"; then
        if .venv/bin/python -c "
import logging; logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')
from skills.feishu_skill import sync_feishu_sources
stats = sync_feishu_sources()
if stats['new'] + stats['updated'] > 0:
    print(f'[SYNC] 新增{stats[\"new\"]} 更新{stats[\"updated\"]}')
" >> "$LOG_FILE" 2>&1; then
            feishu_ok=true
        fi
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ 飞书同步跳过：DNS 持续不通" >> "$LOG_FILE"
    fi

    # Step 1: 发送每日精选（带 SMTP 重试）
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 📤 开始每日精选推送..." >> "$LOG_FILE"

    if .venv/bin/python -c "
import logging; logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')
from skills.daily_digest_skill import send_daily_digest
send_daily_digest()
" >> "$LOG_FILE" 2>&1; then
        push_ok=true
    fi

    # SMTP 重试：如果邮件失败可能是端口问题，尝试 587 端口
    if [ "$push_ok" != true ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠️ 首次推送失败，尝试 SMTP 端口切换..." >> "$LOG_FILE"
        if [ "${SMTP_PORT:-465}" = "465" ]; then
            export SMTP_PORT=587
        else
            export SMTP_PORT=465
        fi
        if .venv/bin/python -c "
import logging; logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')
from skills.daily_digest_skill import send_daily_digest
send_daily_digest()
" >> "$LOG_FILE" 2>&1; then
            push_ok=true
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ SMTP 端口切换后推送成功 (port=${SMTP_PORT})" >> "$LOG_FILE"
        fi
    fi

    # 结果记录
    if [ "$push_ok" = true ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ 每日汇总推送成功" >> "$LOG_FILE"
        clear_failure
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ 每日汇总推送失败" >> "$LOG_FILE"
        record_failure
        exit 1
    fi
}

main "$@"
