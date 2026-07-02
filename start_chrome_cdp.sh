#!/usr/bin/env bash
# 启动 Chrome 并开启远程调试端口（供 CDPEngine 连接）
# 用法: bash start_chrome_cdp.sh

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE_DIR="$HOME/chrome-debug-profile"
DEBUG_PORT=9222

# 检查 Chrome 是否已在运行
if curl -s http://localhost:$DEBUG_PORT/json/version > /dev/null 2>&1; then
    echo "Chrome CDP 已在运行: http://localhost:$DEBUG_PORT"
    echo ""
    echo "使用方法:"
    echo "  python -c \"from skills.job_search_skill import CDPEngine; eng = CDPEngine(); print(eng.search(['产品经理']))\""
    exit 0
fi

if [ ! -f "$CHROME" ]; then
    echo "Error: Chrome not found at $CHROME"
    exit 1
fi

echo "启动 Chrome (调试模式)..."
echo "  → 调试端口: $DEBUG_PORT"
echo "  → 用户目录: $PROFILE_DIR"
echo ""
echo "请在打开的 Chrome 中:"
echo "  1. 登录 zhipin.com"
echo "  2. 保持 Chrome 不关闭"
echo "  3. 运行 job_search CDP 引擎"
echo ""

nohup "$CHROME" \
    --remote-debugging-port=$DEBUG_PORT \
    --user-data-dir="$PROFILE_DIR" \
    --no-first-run \
    > /dev/null 2>&1 &

sleep 2

if curl -s http://localhost:$DEBUG_PORT/json/version > /dev/null 2>&1; then
    echo "Chrome CDP 已就绪"
else
    echo "Chrome 启动中，请稍候..."
fi
