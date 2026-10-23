#!/usr/bin/env bash
# Proves a backup restores: unzips it to a scratch file, runs integrity_check and prints row counts.
# Never touches the live database. Usage: restore-test.sh [backup.db.gz]   (default: newest in ~/backups/cartbridge)
set -euo pipefail
DIR="$HOME/backups/cartbridge"
FILE="${1:-$(ls -1t "$DIR"/cartbridge-*.db.gz | head -1)}"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
gunzip -c "$FILE" > "$T/restore.db"
python3 - "$T/restore.db" <<'PY'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "integrity_check failed"
have = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
for t in ("users", "api_keys", "platform_access", "walmart_credentials"):
    print(f"{t}: {c.execute(f'SELECT count(*) FROM {t}').fetchone()[0]} rows" if t in have else f"{t}: (no such table)")
print("restore test ok")
PY
