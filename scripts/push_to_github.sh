#!/usr/bin/env bash
# 把本仓库推到 GitHub。
# 用法：bash scripts/push_to_github.sh <GitHub用户名> [仓库名] [public|private]
# 凭据：优先 gh 登录态；否则用 GITHUB_TOKEN（一次性 URL 推送，不写入 .git/config）
set -euo pipefail

cd "$(dirname "$0")/.."

OWNER="${1:-${GITHUB_OWNER:-}}"
REPO="${2:-three-body-ai-team}"
VISIBILITY="${3:-public}"
TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-}}"

if [[ "$VISIBILITY" != "public" && "$VISIBILITY" != "private" ]]; then
  echo "可见性只能是 public 或 private" >&2; exit 1
fi

if [[ ! -d .git ]]; then
  git init -b main
fi
git add .
git commit -m "feat: 三体 AI 内容工作室 · Grok 多智能体协作引擎" >/dev/null 2>&1 || echo "没有新的改动，沿用已有提交"

if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  echo "使用 gh 创建并推送仓库 …"
  gh repo create "$OWNER/$REPO" "--$VISIBILITY" --source=. --remote=origin --push \
    || { git remote add origin "https://github.com/$OWNER/$REPO.git" 2>/dev/null || true; git push -u origin main; }
else
  if [[ -z "$OWNER" || -z "$TOKEN" ]]; then
    echo "缺少凭据。二选一：" >&2
    echo "  1) 安装并登录 GitHub CLI：brew install gh && gh auth login" >&2
    echo "  2) 设置环境变量：export GITHUB_OWNER=<用户名> GITHUB_TOKEN=<token>" >&2
    echo "     token 需要 repo 权限（建仓 + push）。" >&2
    exit 1
  fi
  echo "使用 REST API 创建仓库 …"
  PRIVATE=false; [[ "$VISIBILITY" == "private" ]] && PRIVATE=true
  curl -fsS -X POST "https://api.github.com/user/repos" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Accept: application/vnd.github+json" \
    -d "{\"name\":\"$REPO\",\"private\":$PRIVATE,\"description\":\"Grok 驱动的七角色多智能体协作引擎\"}" \
    >/dev/null || echo "仓库可能已存在，继续推送"
  git push "https://x-access-token:${TOKEN}@github.com/${OWNER}/${REPO}.git" HEAD:refs/heads/main
  git remote add origin "https://github.com/${OWNER}/${REPO}.git" 2>/dev/null || \
    git remote set-url origin "https://github.com/${OWNER}/${REPO}.git"
fi

echo ""
echo "完成：https://github.com/${OWNER:-<用户名>}/${REPO}"
echo "下一步：Settings → Secrets → Actions 添加 XAI_API_KEY，然后开一个 Issue 写 /team run <任务>"
