#!/usr/bin/env bash
# start_wechat.sh — 一键启动企业微信接入服务
# 用法: bash start_wechat.sh [all|sync|poller|webhook]
#   all    - 启动全部服务（默认）：云端同步 + 客服轮询
#   sync   - 仅启动云端同步（从 Cloudflare Worker 拉取企微消息 → 本地 ETL）
#   poller - 仅启动微信客服轮询服务（方案B，不需要隧道）
#   webhook- 仅启动本地 Webhook（调试备用，需要隧道）

set -e

# 退出 conda 环境（避免干扰虚拟环境）
conda deactivate 2>/dev/null || true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

MODE="${1:-all}"

# 激活虚拟环境
source .venv/bin/activate

# 检查依赖
python -c "import flask" 2>/dev/null || pip install flask
python -c "from Crypto.Cipher import AES" 2>/dev/null || pip install pycryptodome
python -c "import requests" 2>/dev/null || pip install requests

# 确保目录
mkdir -p logs data/inbox data/processed data/failed

# 清除代理
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy all_proxy

export PYTHONPATH="$SCRIPT_DIR/src"
export PADDLE_PDX_CACHE_HOME="$SCRIPT_DIR/.paddleocr_cache"

echo ""
echo "====================================================="
echo "  Knowledge Agent - 微信接入服务"
echo "  模式: $MODE"
echo "====================================================="

PIDS=()

# ── 云端同步（从 Cloudflare Worker 拉取积压消息 → 本地 ETL）───
if [ "$MODE" = "all" ] || [ "$MODE" = "sync" ]; then
    echo ""
    echo "[启动] 实时云端同步服务（每60s轮询，有消息30s加速）..."
    echo "  ✅ Mac 关机时消息自动排队到 D1"
    echo "  ✅ 开机后自动拉取处理"
    echo "  ✅ URL 自动展开抓取"
    python src/skills/cloud_sync_skill.py --loop --interval 60 &
    SYNC_PID=$!
    PIDS+=($SYNC_PID)
    sleep 2
    echo "[就绪] 云端同步服务已启动 (PID=$SYNC_PID)"
fi

# ── 启动微信客服轮询服务（方案B，推荐）─────────────────────
if [ "$MODE" = "all" ] || [ "$MODE" = "poller" ]; then
    echo ""
    echo "[启动] 微信客服消息轮询服务（方案B·主动拉取）..."
    echo "  ✅ 不需要内网穿透"
    echo "  ✅ 不需要配置回调 URL"
    python src/skills/wechat_kf_poller.py &
    KF_PID=$!
    PIDS+=($KF_PID)
    sleep 3
    echo "[就绪] 微信客服轮询服务已启动 (PID=$KF_PID)"
fi

# ── 本地 Webhook（调试备用，需要 Cloudflare Tunnel）─────────
if [ "$MODE" = "webhook" ]; then
    CLOUDFLARED="$SCRIPT_DIR/cloudflared"
    if [ ! -f "$CLOUDFLARED" ]; then
        echo "[安装] 正在下载 cloudflared..."
        curl -sL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz" | tar xz -C "$SCRIPT_DIR"
        echo "[完成] cloudflared 已安装"
    fi

    echo ""
    echo "[启动] 本地 Webhook 调试模式 (:5001) ..."
    echo "  ⚠️  此模式仅用于调试，生产环境请用 sync 模式"
    python src/skills/wechat_webhook.py &
    APP_PID=$!
    PIDS+=($APP_PID)

    APP_READY=0
    for i in $(seq 1 8); do
        sleep 2
        if curl -sf http://localhost:5001/health > /dev/null 2>&1; then
            APP_READY=1
            break
        fi
        echo "  [等待] Flask 启动中（${i}/8）..."
    done

    if [ $APP_READY -eq 1 ]; then
        echo "[就绪] 本地 Webhook OK (PID=$APP_PID)"

        # 启动隧道
        echo "[启动] Cloudflare 隧道 (app → :5001) ..."
        "$CLOUDFLARED" tunnel --url "http://localhost:5001" > "$SCRIPT_DIR/logs/tunnel_app.log" 2>&1 &
        TUNNEL_PID=$!
        PIDS+=($TUNNEL_PID)
        sleep 6

        URL=$(grep -o 'https://[a-z0-9.-]*\.trycloudflare\.com' "$SCRIPT_DIR/logs/tunnel_app.log" | head -1)
        if [ -n "$URL" ]; then
            echo "[隧道就绪] app: $URL"
            echo "$URL" > "$SCRIPT_DIR/data/.tunnel_url_app.txt"
        else
            echo "[警告] 隧道建立中，查看日志: tail -f $SCRIPT_DIR/logs/tunnel_app.log"
        fi
    else
        echo "[错误] 本地 Webhook 启动失败，请检查日志"
        kill $APP_PID 2>/dev/null; exit 1
    fi
fi

# ── 输出汇总信息 ───────────────────────────────────────────────
echo ""
echo "====================================================="
echo "  服务状态汇总"
echo "====================================================="

if [ "$MODE" = "all" ] || [ "$MODE" = "sync" ]; then
    echo ""
    echo "  ☁️  云端同步（企微自建应用主入口）："
    echo "     模式: 企微推送 → Cloudflare Worker → D1排队 → 本地拉取 → ETL"
    echo "     日志: tail -f logs/cloud_sync.log"
fi

if [ "$MODE" = "all" ] || [ "$MODE" = "poller" ]; then
    echo ""
    echo "  💬 微信客服轮询（个人微信发消息用）："
    echo "     模式: 方案B · 主动拉取（无需隧道）"
    echo "     日志: tail -f logs/wechat_kf.log"
fi

if [ "$MODE" = "webhook" ]; then
    APP_URL=$(cat "$SCRIPT_DIR/data/.tunnel_url_app.txt" 2>/dev/null || echo "未获取")
    echo ""
    echo "  📱 本地 Webhook（调试模式）："
    echo "     回调URL: ${APP_URL}/wechat/callback"
    echo "     ⚠️  Mac 关机消息会丢失，生产环境请用 sync 模式"
fi

echo ""
echo "====================================================="
echo "  所有进程已启动，按 Ctrl+C 停止全部服务"
echo "====================================================="
echo ""

# 清理函数
cleanup() {
    echo ""
    echo "[停止] 正在关闭所有服务..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null && echo "  已停止 PID=$pid"
    done
    exit 0
}

trap cleanup INT TERM
wait
