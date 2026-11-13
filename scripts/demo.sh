#!/usr/bin/env bash
# 离线跑一次完整演示并打开协作看板（不需要任何 API Key）
# 用法：bash scripts/demo.sh [trio|duo|full]   默认 trio
set -euo pipefail
cd "$(dirname "$0")/.."

TEAM="${1:-trio}"
RUN_DIR="runs/demo-$TEAM"

python3 -m sanbot run --mock --team "$TEAM" --meetings 2 --run-dir "$RUN_DIR"

echo ""
echo "编制：$TEAM"
echo "协作看板：$(pwd)/$RUN_DIR/dashboard.html"
if command -v open >/dev/null 2>&1; then
  open "$RUN_DIR/dashboard.html"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$RUN_DIR/dashboard.html"
fi
