#!/bin/bash
# 双击即可：自动从剪贴板读取 GitHub Token 并推送整个仓库。
# 不需要敲任何命令；Token 不显示、不保存。
cd "$(dirname "$0")" || exit 1

echo "=============================================="
echo "   三体 AI 团队 · 一键推送到 GitHub"
echo "=============================================="
echo ""

if bash scripts/finish_push.sh --clipboard; then
  echo ""
  echo "✅ 推送完成，仓库地址（可能需刷新网页）："
  echo "   https://github.com/Fuxizengxiao520/three-body-ai-team"
else
  echo ""
  echo "还没拿到 Token，现在打开生成页面……"
  bash scripts/finish_push.sh --open
  echo ""
  echo "在网页上：登录 → 拉到底点 Generate token → 点「复制」"
  echo "（如果这台电脑打不开 github.com，就用手机浏览器打开同样的链接）"
  echo "复制后重新双击本文件即可，不用敲任何命令。"
fi

echo ""
read -r -p "按回车键关闭窗口…" _
