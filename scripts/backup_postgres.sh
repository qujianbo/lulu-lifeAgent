#!/usr/bin/env bash
set -Eeuo pipefail

# Create a compressed PostgreSQL backup from the Docker Compose database service.
SSH_TARGET="${SSH_TARGET:-aliyun-life-agent}"
REMOTE_DIR="${REMOTE_DIR:-/home/admin/lulu-lifeAgent}"
BACKUP_DIR="${BACKUP_DIR:-/home/admin/lulu-lifeAgent/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"

run_remote() {
  ssh "$SSH_TARGET" "cd '$REMOTE_DIR' && $*"
}

timestamp="$(date +%Y%m%d_%H%M%S)"
file_name="life_agent_${timestamp}.sql.gz"

echo "==> Backup target: $SSH_TARGET:$BACKUP_DIR/$file_name"
run_remote "mkdir -p '$BACKUP_DIR'"
run_remote "docker compose exec -T postgres pg_dump -U life_agent -d life_agent | gzip > '$BACKUP_DIR/$file_name'"
run_remote "find '$BACKUP_DIR' -name 'life_agent_*.sql.gz' -mtime +$RETENTION_DAYS -delete"
run_remote "ls -lh '$BACKUP_DIR/$file_name'"
echo "==> Backup complete"
