#!/usr/bin/env bash
# Consistent daily backup of the CartBridge SQLite DB. Run ON THE SERVER (host), e.g. from cron.
# Uses SQLite's online backup API inside the container, so it is safe while the app is running.
# Usage: backup-sqlite.sh [backup_dir] [keep_days]     (defaults: ~/backups/cartbridge, 14)
set -euo pipefail
DIR="${1:-$HOME/backups/cartbridge}"
KEEP="${2:-14}"
C="${CARTBRIDGE_CONTAINER:-cartbridge}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$DIR"
chmod 700 "$DIR"
umask 077
docker exec "$C" python -c "
import sqlite3, sys
src = sqlite3.connect('/data/cartbridge.db'); dst = sqlite3.connect('/tmp/backup.db')
src.backup(dst); dst.close(); src.close()
chk = sqlite3.connect('/tmp/backup.db').execute('PRAGMA integrity_check').fetchone()[0]
sys.exit(0 if chk == 'ok' else 'integrity_check: ' + chk)"
docker cp "$C:/tmp/backup.db" "$DIR/cartbridge-$STAMP.db"
docker exec "$C" rm -f /tmp/backup.db
gzip -f "$DIR/cartbridge-$STAMP.db"
# Rotation: backups older than KEEP days are removed.
find "$DIR" -name 'cartbridge-*.db.gz' -mtime +"$KEEP" -delete
echo "backup ok: $DIR/cartbridge-$STAMP.db.gz"
