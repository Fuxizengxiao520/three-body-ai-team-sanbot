#!/usr/bin/env bash
# 一键收尾：建仓 → 上传全部文件 → 生成一次提交 → 验证。
# 走纯 REST API（scripts/push_via_api.py），只访问 api.github.com，
# 不依赖 gh、不走 git push；Token 只在进程内存，不落盘、不回显、不进日志。
#
# 用法：
#   bash scripts/finish_push.sh --open        打开 Token 生成页（权限已预填）
#   bash scripts/finish_push.sh              自动取 Token：环境变量 → .env → 剪贴板 → 手动粘贴
#   bash scripts/finish_push.sh --clipboard  强制只从剪贴板读取（适合非交互）
#   bash scripts/finish_push.sh --manual     忽略剪贴板，手动粘贴
#   bash scripts/finish_push.sh --dry-run    只预览将上传的文件，不联网、不需要 Token
#   bash scripts/finish_push.sh --private    建私有仓库
#
# 可选环境变量：GITHUB_TOKEN / GITHUB_OWNER / GITHUB_REPO / VISIBILITY
set -euo pipefail

cd "$(dirname "$0")/.."

TOKEN_URL="https://github.com/settings/tokens/new?description=three-body-ai-team&scopes=repo,workflow"
TOKEN_RE='^(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})$'

USE_CLIPBOARD=auto
IS_DRY=0
VIS="${VISIBILITY:-}"
PASSTHRU=()

for arg in "$@"; do
  case "$arg" in
    --open)
      /usr/bin/open "$TOKEN_URL" 2>/dev/null || true
      echo "已在默认浏览器打开 Token 生成页："
      echo "  $TOKEN_URL"
      echo "登录后确认勾选 repo + workflow，拉到底点 Generate token，再点「复制」。"
      echo "（若这台机器打不开 github.com，用手机浏览器打开同一链接也行，复制后经通用剪贴板同步到 Mac。）"
      exit 0
      ;;
    --clipboard) USE_CLIPBOARD=force ;;
    --manual)    USE_CLIPBOARD=off ;;
    --private)   VIS=private ;;
    --dry-run)   IS_DRY=1; PASSTHRU+=("$arg") ;;
    *)           PASSTHRU+=("$arg") ;;
  esac
done

token="${GITHUB_TOKEN:-}"

# dry-run 只列文件，跳过所有凭据获取
if [[ "$IS_DRY" == 0 ]]; then
  # 项目 .env（只取值，不打印）
  if [[ -z "$token" && -f .env ]]; then
    token="$(grep -m1 -E '^(GITHUB_TOKEN|GH_TOKEN)=' .env 2>/dev/null | cut -d= -f2- | tr -d '"'"'"'[:space:]' || true)"
  fi

  # 剪贴板：只在没有其他来源时检查，内容绝不回显
  if [[ -z "$token" && "$USE_CLIPBOARD" != "off" ]]; then
    clip="$(pbpaste 2>/dev/null | tr -d '[:space:]' || true)"
    if [[ -n "$clip" && "$clip" =~ $TOKEN_RE ]]; then
      echo "检测到剪贴板里有 GitHub Token，直接使用（内容不显示）。"
      token="$clip"
    elif [[ "$USE_CLIPBOARD" == "force" ]]; then
      echo "剪贴板里没有有效的 GitHub Token。" >&2
      echo "先运行 bash scripts/finish_push.sh --open 生成并复制，或直接把 Token 贴给我。" >&2
      exit 1
    fi
  fi

  # 最后才需要手动粘贴
  if [[ -z "$token" && "$USE_CLIPBOARD" != "force" ]]; then
    if [[ -t 0 ]]; then
      echo "还没有 Token。运行 bash scripts/finish_push.sh --open 可打开生成页面。"
      printf '请粘贴 Token（输入不回显，粘贴后按回车）：'
      read -r -s token
      printf '\n'
    else
      echo "未找到 Token，已取消。生成并复制后重跑，或用 --clipboard。" >&2
      echo "  $TOKEN_URL" >&2
      exit 1
    fi
  fi

  if [[ -z "$token" ]]; then
    echo "Token 为空，已取消。" >&2
    exit 1
  fi
fi

ARGS=(--visibility "${VIS:-public}")
if [[ -n "${GITHUB_OWNER:-}" ]]; then ARGS+=(--owner "$GITHUB_OWNER"); fi
if [[ -n "${GITHUB_REPO:-}" ]]; then ARGS+=(--repo "$GITHUB_REPO"); fi

if [[ -n "$token" ]]; then export GITHUB_TOKEN="$token"; fi
exec python3 scripts/push_via_api.py "${ARGS[@]}" ${PASSTHRU[@]+"${PASSTHRU[@]}"}
