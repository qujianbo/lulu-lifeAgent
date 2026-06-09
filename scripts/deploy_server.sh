#!/usr/bin/env bash
set -Eeuo pipefail

# Deploy local code to the lightweight server without overwriting server secrets.
SSH_TARGET="${SSH_TARGET:-aliyun-life-agent}"
REMOTE_DIR="${REMOTE_DIR:-/home/admin/lulu-lifeAgent}"
APP_URL="${APP_URL:-http://127.0.0.1:8000}"

BUILD=0
SKIP_MIGRATE=0

usage() {
  cat <<'EOF'
Usage: scripts/deploy_server.sh [options]

Options:
  --build          Rebuild app and scheduler images after syncing code.
  --skip-migrate   Skip alembic migration step.
  -h, --help       Show this help message.

Environment variables:
  SSH_TARGET       SSH target or alias. Default: aliyun-life-agent
  REMOTE_DIR       Remote project directory. Default: /home/admin/lulu-lifeAgent
  APP_URL          Health check URL from server side. Default: http://127.0.0.1:8000
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --build)
      BUILD=1
      shift
      ;;
    --skip-migrate)
      SKIP_MIGRATE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

run_remote() {
  ssh "$SSH_TARGET" "cd '$REMOTE_DIR' && $*"
}

echo "==> Deploy target: $SSH_TARGET:$REMOTE_DIR"

if [[ -n "$(git status --short)" ]]; then
  echo "==> Local worktree has uncommitted changes; deploying current files."
fi

echo "==> Syncing source files"
COPYFILE_DISABLE=1 tar \
  --exclude='.git' \
  --exclude='.env' \
  --exclude='.venv' \
  --exclude='.pytest_cache' \
  --exclude='.ruff_cache' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='logs' \
  --exclude='postgres_data' \
  --exclude='redis_data' \
  --exclude='DATABASE_DESIGN.md' \
  --exclude='PRD.md' \
  --exclude='PROJECT_IMPLEMENTATION_CHECKLIST.md' \
  --exclude='TECHNICAL_IMPLEMENTATION.md' \
  -czf - . \
  | ssh "$SSH_TARGET" "mkdir -p '$REMOTE_DIR' && tar -xzf - -C '$REMOTE_DIR'"

if [[ "$SKIP_MIGRATE" -eq 0 ]]; then
  echo "==> Running database migrations"
  run_remote "docker compose run --rm migrate"
fi

if [[ "$BUILD" -eq 1 ]]; then
  echo "==> Rebuilding and starting app services"
  run_remote "docker compose up -d --build app scheduler"
else
  echo "==> Starting and restarting app services"
  run_remote "docker compose up -d app scheduler && docker compose restart app scheduler"
fi

echo "==> Waiting for app health"
run_remote "for i in \$(seq 1 20); do curl -fsS '$APP_URL/healthz' >/dev/null && exit 0; sleep 2; done; curl -fsS '$APP_URL/healthz'"

echo "==> Service status"
run_remote "docker compose ps"

echo "==> Deploy complete"
