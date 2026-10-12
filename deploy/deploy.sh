#!/usr/bin/env bash
# Usage: DEPLOY_HOST=my-server deploy/deploy.sh  (run from anywhere). Syncs backend + deploy files to $DEPLOY_HOST and restarts.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
H="${DEPLOY_HOST:?set DEPLOY_HOST to your ssh host alias}"
D=/home/ubuntu/cartbridge
ssh $H "mkdir -p $D/backend"
rsync -az --delete --exclude .venv --exclude __pycache__ --exclude tests --exclude '.env' --exclude '*.db' --exclude '*.pem' "$ROOT/backend/" $H:$D/backend/
scp "$HERE/docker-compose.prod.yml" "$HERE/Caddyfile" $H:$D/
ssh $H "cd $D && docker compose -f docker-compose.prod.yml up -d --build && docker compose -f docker-compose.prod.yml ps"
