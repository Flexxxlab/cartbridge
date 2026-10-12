#!/usr/bin/env bash
# Usage: deploy/deploy.sh  (run from anywhere). Syncs backend + deploy files to duck-prod and restarts.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
H=duck-prod
D=/home/ubuntu/cartbridge
ssh $H "mkdir -p $D/backend"
rsync -az --delete --exclude .venv --exclude __pycache__ --exclude tests --exclude '.env' --exclude '*.db' --exclude '*.pem' "$ROOT/backend/" $H:$D/backend/
scp "$HERE/docker-compose.prod.yml" "$HERE/Caddyfile" $H:$D/
ssh $H "cd $D && docker compose -f docker-compose.prod.yml up -d --build && docker compose -f docker-compose.prod.yml ps"
