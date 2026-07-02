#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 检查虚拟环境
if [ ! -d ".venv" ]; then
    echo "Error: .venv not found. Create it first: python3 -m venv .venv"
    exit 1
fi

source .venv/bin/activate
export PYTHONPATH="$SCRIPT_DIR/src"

# 确保依赖已安装
pip install -q flask 2>/dev/null || true

PORT="${DASHBOARD_PORT:-5000}"

echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║     Knowledge Agent OS — Dashboard       ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""
echo "  → http://localhost:${PORT}"
echo "  → Press Ctrl+C to stop"
echo ""

python src/web/dashboard.py
