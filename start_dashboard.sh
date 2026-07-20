#!/usr/bin/env bash
# AIOS Dashboard — 双击 .command 文件或运行此脚本启动
set -e
cd "$(dirname "$0")"
source .venv/bin/activate
python dashboard.py
