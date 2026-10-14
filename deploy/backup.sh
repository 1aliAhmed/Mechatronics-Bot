#!/usr/bin/env bash
# Daily data backup: consistent SQLite snapshot + uploaded/generated files + logs.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/megatronics}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/megatronics}"
KEEP="${KEEP:-7}"

if [[ $EUID -ne 0 ]]; then echo "Run with sudo: sudo bash deploy/backup.sh" >&2; exit 1; fi

stamp=$(date -u +%Y%m%d-%H%M)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

APP_DIR="$APP_DIR" DB_OUT="$work/bot.db" "$APP_DIR/.venv/bin/python" - <<'PY'
import os
import sqlite3

source = sqlite3.connect(os.path.join(os.environ["APP_DIR"], "data", "bot.db"))
target = sqlite3.connect(os.environ["DB_OUT"])
source.backup(target)
target.close()
source.close()
PY

mkdir -p "$BACKUP_DIR"
tar -czf "$BACKUP_DIR/megatronics-$stamp.tar.gz" -C "$work" bot.db -C "$APP_DIR" data/files data/logs 2>/dev/null \
  || tar -czf "$BACKUP_DIR/megatronics-$stamp.tar.gz" -C "$work" bot.db -C "$APP_DIR" data/files
chmod 600 "$BACKUP_DIR/megatronics-$stamp.tar.gz"
ls -1t "$BACKUP_DIR"/megatronics-*.tar.gz | tail -n +$((KEEP + 1)) | xargs -r rm -f
echo "backup written: $BACKUP_DIR/megatronics-$stamp.tar.gz"
