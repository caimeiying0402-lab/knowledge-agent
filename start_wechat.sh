#!/usr/bin/env bash
# start_wechat.sh — 一键启动企业微信接入服务
# 用法: bash start_wechat.sh [all|app|kf|poller]
#   all    - 启动全部服务（默认）：自建应用Webhook + 客服轮询
#   app    - 仅启动企业微信自建应用 webhook（需要隧道）
#   kf     - 仅启动微信客服 Webhook（需要隧道，旧版回调模式）
#   poller - 仅启动微信客服轮询服务（方案B，不需要隧道，推荐）

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

# ── 启动企业微信自建应用 Webhook（端口 5001）─────────────────
if [ "$MODE" = "all" ] || [ "$MODE" = "app" ]; then
    # 检查 cloudflared
    CLOUDFLARED="$SCRIPT_DIR/cloudflared"
    if [ ! -f "$CLOUDFLARED" ]; then
        echo "[安装] 正在下载 cloudflared..."
        curl -sL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz" | tar xz -C "$SCRIPT_DIR"
        echo "[完成] cloudflared 已安装"
    fi

    echo ""
    echo "[启动] 企业微信自建应用 Webhook (:5001) ..."
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
        echo "[就绪] 自建应用 Webhook OK (PID=$APP_PID)"
    else
        echo "[错误] 自建应用 Webhook 启动失败，请检查日志"
        kill $APP_PID 2>/dev/null; exit 1
    fi
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

# ── 启动微信客服 Webhook 旧版（需要隧道）───────────────────
if [ "$MODE" = "kf" ]; then
    CLOUDFLARED="$SCRIPT_DIR/cloudflared"
    if [ ! -f "$CLOUDFLARED" ]; then
        echo "[安装] 正在下载 cloudflared..."
        curl -sL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz" | tar xz -C "$SCRIPT_DIR"
    fi

    echo ""
    echo "[启动] 微信客服 Webhook (:5002) ..."
    python src/skills/wechat_kf_service.py &
    KF_PID=$!
    PIDS+=($KF_PID)

    KF_READY=0
    for i in $(seq 1 8); do
        sleep 2
        if curl -sf http://localhost:5002/health > /dev/null 2>&1; then
            KF_READY=1
            break
        fi
        echo "  [等待] Flask 启动中（${i}/8）..."
    done

    if [ $KF_READY -eq 1 ]; then
        echo "[就绪] 微信客服 Webhook OK (PID=$KF_PID)"
    else
        echo "[错误] 微信客服 Webhook 启动失败，请检查日志: logs/wechat_kf.log"
        kill $KF_PID 2>/dev/null
        if [ "$MODE" = "kf" ]; then exit 1; fi
    fi
fi

# ── 启动 Cloudflare Tunnel(s) ───────────────────────────────────
start_tunnel() {
    local port=$1
    local name=$2
    local log_file="$SCRIPT_DIR/logs/tunnel_${name}.log"

    echo "[启动] Cloudflare 隧道 (${name} → :${port}) ..."
    "$CLOUDFLARED" tunnel --url "http://localhost:${port}" > "$log_file" 2>&1 &
    TUNNEL_PID=$!
    PIDS+=($TUNNEL_PID)
    sleep 6

    URL=$(grep -o 'https://[a-z0-9.-]*\.trycloudflare\.com' "$log_file" | head -1)
    if [ -n "$URL" ]; then
        echo "[隧道就绪] ${name}: $URL"
        echo "$URL" > "$SCRIPT_DIR/data/.tunnel_url_${name}.txt"
    else
        echo "[警告] ${name} 隧道建立中，查看日志: tail -f $log_file"
    fi
    echo "$TUNNEL_PID"
}

if [ "$MODE" = "all" ] || [ "$MODE" = "app" ] || [ "$MODE" = "kf" ]; then
    TUNNEL_PIDS=""
    if [ "$MODE" = "all" ] || [ "$MODE" = "app" ]; then
        PID=$(start_tunnel 5001 "app")
        TUNNEL_PIDS="$TUNNEL_PIDS $PID"
    fi
    if [ "$MODE" = "kf" ]; then
        PID=$(start_tunnel 5002 "kf")
        TUNNEL_PIDS="$TUNNEL_PIDS $PID"
    fi
fi

# ── 输出汇总信息 ───────────────────────────────────────────────
echo ""
echo "====================================================="
echo "  服务状态汇总"
echo "====================================================="

if [ "$MODE" = "all" ] || [ "$MODE" = "app" ]; then
    APP_URL=$(cat "$SCRIPT_DIR/data/.tunnel_url_app.txt" 2>/dev/null || echo "未获取")
    echo ""
    echo "  📱 自建应用（企微成员发消息用）："
    echo "     回调URL: ${APP_URL}/wechat/callback"
    echo "     配置位置: 应用管理 → 知识收集助手 → 接收消息"
fi

if [ "$MODE" = "all" ] || [ "$MODE" = "poller" ]; then
    echo ""
    echo "  💬 微信客服轮询（个人微信发消息用）："
    echo "     模式: 方案B · 主动拉取（无需隧道）"
    echo "     日志: tail -f logs/wechat_kf.log"
    echo ""
    echo "     使用方式："
    echo "     1. 在微信中搜索「富婆OS客服」或扫码进入客服会话"
    echo "     2. 发送文字/图片/链接即可触发采集"
    echo "     3. 结果自动写入飞书多维表格"
fi

if [ "$MODE" = "kf" ]; then
    KF_URL=$(cat "$SCRIPT_DIR/data/.tunnel_url_kf.txt" 2>/dev/null || echo "未获取")
    echo ""
    echo "  💬 微信客服 Webhook（旧版回调模式）："
    echo "     回调URL: ${KF_URL}/wechat/kf/callback"
    echo "     配置位置: 企业微信管理后台 → 微信客服 → 开发配置/API"
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
