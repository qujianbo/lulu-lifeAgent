#!/usr/bin/env bash
set -Eeuo pipefail

# Run server-side smoke checks for the non-WeChat MVP backend.
SSH_TARGET="${SSH_TARGET:-aliyun-life-agent}"
REMOTE_DIR="${REMOTE_DIR:-/home/admin/lulu-lifeAgent}"
APP_URL="${APP_URL:-http://127.0.0.1:8000}"
ADMIN_TOKEN="${ADMIN_TOKEN:-}"
RUN_CHAT="${RUN_CHAT:-1}"

run_remote() {
  ssh "$SSH_TARGET" "$*"
}

load_remote_admin_token() {
  if [[ -n "$ADMIN_TOKEN" ]]; then
    return
  fi
  ADMIN_TOKEN="$(run_remote "cd '$REMOTE_DIR' && sed -n 's/^ADMIN_TOKEN=//p' .env | tail -1" || true)"
}

remote_curl() {
  local method="$1"
  local path="$2"
  local body="${3:-}"
  local admin_header=""
  if [[ -n "$ADMIN_TOKEN" ]]; then
    admin_header="-H 'x-admin-token: $ADMIN_TOKEN'"
  fi
  if [[ -n "$body" ]]; then
    run_remote "curl -fsS -X '$method' '$APP_URL$path' -H 'content-type: application/json' $admin_header --data-binary '$body'"
  else
    run_remote "curl -fsS -X '$method' '$APP_URL$path' $admin_header"
  fi
}

load_remote_admin_token

echo "==> Smoke target: $SSH_TARGET $APP_URL"
echo "==> Checking healthz"
remote_curl GET /healthz >/dev/null

echo "==> Checking readyz"
remote_curl GET /readyz >/dev/null

echo "==> Checking debug page"
remote_curl GET /debug/chat | grep -q "生活管家 Agent 调试"

echo "==> Checking stats"
remote_curl GET /api/local/stats >/dev/null

if [[ "$RUN_CHAT" == "1" ]]; then
  echo "==> Checking local Agent chat"
  remote_curl POST /api/local/chat '{"message":"怎么安排今天的工作？"}' | grep -q '"intent"'
fi

echo "==> Smoke checks passed"
