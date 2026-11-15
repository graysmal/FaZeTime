#!/usr/bin/env bash
# Deploy services/api to the Pi: back up the DB with the code that is running, copy the
# new code (plain file copy, HANDOFF runbook), restart (migrations apply at startup) and
# check health. Usage: infra/pi/deploy_api.sh [backup-tag]
set -euo pipefail
HOST="${FAZETIME_PI:-fazetime@fazetime}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
TAG="${1:-deploy}"
STAMP="$(date +%Y%m%d-%H%M%S)"

echo "== backup (running code) =="
ssh "$HOST" "cd ~/fazetime/services/api && FAZETIME_DATA_DIR=~/fazetime-data .venv/bin/python -m fazetime_api backup ~/fazetime-data/backup-pre-${TAG}-${STAMP}.db && ls -l ~/fazetime-data/backup-pre-${TAG}-${STAMP}.db"

echo "== copy services/api =="
rsync -a --exclude .venv --exclude __pycache__ --exclude 'var/' --exclude .pytest_cache \
  "$REPO/services/api/" "$HOST:fazetime/services/api/"

echo "== restart =="
ssh "$HOST" "cd ~/fazetime/services/api && scripts/pi_run.sh restart && scripts/pi_run.sh status"

echo "== health =="
curl -fsS --max-time 5 "http://${HOST#*@}:8000/healthz"; echo
