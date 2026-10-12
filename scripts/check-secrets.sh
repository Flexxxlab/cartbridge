#!/usr/bin/env bash
# Blocks commits that contain secrets or forbidden files. Run automatically by .githooks/pre-commit.
set -euo pipefail
fail=0

# 1. Forbidden file names in the staged set.
bad=$(git diff --cached --name-only --diff-filter=ACMR | grep -E '(^|/)(\.env(\..*)?|.*\.(pem|key|p8|p12|pfx|jks|keystore|db|sqlite3?)|WM_IO_.*|.*_key_pair.*|id_rsa.*|CLAUDE\.md)$' | grep -v '\.env\.example$' || true)
if [ -n "$bad" ]; then echo "BLOCKED: forbidden files staged:"; echo "$bad"; fail=1; fi

# 2. Secret-looking content in staged additions.
added=$(git diff --cached -U0 --diff-filter=ACMR | grep -E '^\+[^+]' || true)
pat='-----BEGIN [A-Z ]*PRIVATE KEY-----|cb_[A-Za-z0-9_-]{24,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|ghp_[A-Za-z0-9]{30,}|xox[baprs]-[A-Za-z0-9-]{10,}|sk-[A-Za-z0-9]{32,}|(SMTP_PASSWORD|WALMART_CONSUMER_ID|SECRET_KEY)=[^ #]{12,}'
hits=$(printf '%s\n' "$added" | grep -nE -e "$pat" | grep -v 'replace-with' || true)
if [ -n "$hits" ]; then echo "BLOCKED: secret-looking content in staged changes:"; echo "$hits" | cut -c1-120; fail=1; fi

[ $fail -eq 0 ] || { echo "Commit aborted. Remove the above (or unstage it)."; exit 1; }
