#!/usr/bin/env bash
# ============================================================
# 岗位匹配 — 一键启动脚本
# ============================================================
set -e
cd "$(dirname "$0")"

VENV=".venv/bin/activate"
if [ ! -f "$VENV" ]; then
    echo "❌ 虚拟环境不存在，请先运行: python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

source "$VENV"
export PYTHONPATH="$PWD/src"

# 解析参数
MODE="manual"
ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --file|-f)
            ARGS+=("--jd-file" "$2")
            shift 2
            ;;
        --search|-s)
            MODE="search"
            shift
            ;;
        --parse|-p)
            ARGS+=("--parse-resume" "$2")
            shift 2
            ;;
        --help|-h)
            echo "岗位匹配引擎 — 使用说明"
            echo ""
            echo "用法: bash match.sh [选项]"
            echo ""
            echo "模式 1 — 手动粘贴 JD（最简单，常用）:"
            echo "  bash match.sh"
            echo "  然后粘贴 JD 文本，输入 EOF 结束，即刻出分"
            echo ""
            echo "模式 2 — 从文件读取 JD:"
            echo "  bash match.sh --file jd.txt"
            echo ""
            echo "模式 3 — 简历解析:"
            echo "  bash match.sh --parse 简历.pdf"
            echo ""
            echo "模式 4 — 自动搜索+匹配+TOP3+简历定制:"
            echo "  先启动 Chrome: bash start_chrome_cdp.sh"
            echo "  手动登录 BOSS/猎聘"
            echo "  bash match.sh --search"
            echo ""
            echo "选项:"
            echo "  --file, -f <path>    从文件读取 JD"
            echo "  --search, -s          自动搜索模式（需 Chrome CDP 已启动）"
            echo "  --parse, -p <path>    解析简历文件"
            echo "  --help, -h            显示帮助"
            exit 0
            ;;
        *)
            ARGS+=("$1")
            shift
            ;;
    esac
done

case "$MODE" in
    manual)
        python -m agents.career_agent "${ARGS[@]}"
        ;;
    search)
        python -m agents.career_agent --search-only --engine cdp --platform both --max-results 15 "${ARGS[@]}"
        ;;
esac
