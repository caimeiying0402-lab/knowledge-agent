#!/usr/bin/env bash
# 启动隔离 Chrome Profile（供 CDPEngine v2 连接）
# 用法: bash start_chrome_cdp.sh
set -e

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SCRAPER_PROFILE="$HOME/.boss-scraper-profile"
REAL_PROFILE="$HOME/Library/Application Support/Google Chrome"
DEBUG_PORT=9222

# ── 检查 Chrome 路径 ──
if [ ! -f "$CHROME" ]; then
    echo "Error: Chrome 未找到于 $CHROME"
    exit 1
fi

# ── 检查是否已在运行 ──
if curl -s http://localhost:$DEBUG_PORT/json/version > /dev/null 2>&1; then
    echo "✅ Chrome CDP 已在运行: http://localhost:$DEBUG_PORT"
    echo ""
    echo "直接使用:"
    echo "  python -c \"from skills.job_search_skill import CDPEngine; eng = CDPEngine(); ...\""
    exit 0
fi

# ── 首次设置：复制 Cookie 到隔离 Profile ──
FIRST_TIME=false
if [ ! -d "$SCRAPER_PROFILE" ]; then
    FIRST_TIME=true
    echo "═══════════════════════════════════════════"
    echo "  首次设置：创建隔离 Chrome Profile"
    echo "═══════════════════════════════════════════"
    echo ""

    # 需要先关闭用户日常的 Chrome（因为要读它的 Cookies 文件）
    if pgrep -x "Google Chrome" > /dev/null 2>&1; then
        echo "⚠️  检测到 Chrome 正在运行。"
        echo ""
        echo "要复制登录态，需要先关闭 Chrome。请选择："
        echo "  1) 自动关闭 Chrome 并继续"
        echo "  2) 跳过 Cookie 复制（需要在新 Chrome 中手动登录 BOSS）"
        echo ""
        read -p "输入 1 或 2: " choice
        case $choice in
            1)
                echo "正在关闭 Chrome..."
                pkill -x "Google Chrome" 2>/dev/null || true
                sleep 3
                ;;
            *)
                echo "跳过 Cookie 复制"
                FIRST_TIME_SKIP_COOKIES=true
                ;;
        esac
    fi

    if [ "$FIRST_TIME_SKIP_COOKIES" != "true" ] && [ -d "$REAL_PROFILE" ]; then
        echo "正在复制 Chrome 登录态到隔离 Profile..."

        mkdir -p "$SCRAPER_PROFILE/Default"
        mkdir -p "$SCRAPER_PROFILE/Default/Network"

        # 只复制必要的认证文件
        cp "$REAL_PROFILE/Default/Cookies" "$SCRAPER_PROFILE/Default/" 2>/dev/null || true
        cp "$REAL_PROFILE/Default/Cookies-journal" "$SCRAPER_PROFILE/Default/" 2>/dev/null || true
        cp "$REAL_PROFILE/Default/Network/Cookies" "$SCRAPER_PROFILE/Default/Network/" 2>/dev/null || true
        cp "$REAL_PROFILE/Local State" "$SCRAPER_PROFILE/" 2>/dev/null || true

        echo "✅ Cookie 已复制到隔离 Profile"
    else
        echo "⚠️  未复制 Cookie，需要在新 Chrome 中手动登录 BOSS"
    fi
    echo ""
fi

# ── 启动隔离 Chrome ──
echo "启动隔离 Chrome（调试端口 $DEBUG_PORT）..."
echo "  Profile: $SCRAPER_PROFILE"

nohup "$CHROME" \
    --remote-debugging-port=$DEBUG_PORT \
    --user-data-dir="$SCRAPER_PROFILE" \
    --no-first-run \
    --no-default-browser-check \
    > /dev/null 2>&1 &

sleep 3

if ! curl -s http://localhost:$DEBUG_PORT/json/version > /dev/null 2>&1; then
    echo "Chrome 启动中..."
    sleep 3
fi

echo ""
echo "═══════════════════════════════════════════"
echo "  Chrome CDP 已就绪"
echo "  → 调试端口: $DEBUG_PORT"
echo "  → 隔离 Profile: $SCRAPER_PROFILE"
echo "═══════════════════════════════════════════"
echo ""

if [ "$FIRST_TIME" = true ] && [ "$FIRST_TIME_SKIP_COOKIES" = "true" ]; then
    echo "📌 请在打开的 Chrome 中登录 zhipin.com"
    echo "   登录后即可开始使用 CDPEngine"
else
    echo "📌 请确认 zhipin.com 已处于登录状态"
    echo "   如未登录请在 Chrome 中手动登录"
fi

echo ""
echo "使用方式:"
echo "  cd $(dirname "$0")"
echo "  PYTHONPATH=src python -c \""
echo "    from skills.job_search_skill import CDPEngine"
echo "    eng = CDPEngine()"
echo "    results = eng.search(['产品经理'], {})"
echo "    print(f'搜索到 {len(results)} 个岗位')"
echo "    eng.stop()"
echo "  \""
echo ""
