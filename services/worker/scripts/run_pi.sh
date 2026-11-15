#!/usr/bin/env bash
# Start the P3 media worker detached on the Pi (setsid + nohup). Log: ~/fazetime-data/worker.log
# Configuration comes from the environment. Secrets (FAZETIME_WORKER_TOKEN) may be kept in
# ~/fazetime-data/worker.env, which must be chmod 600 and is never committed or printed.
# Usage: scripts/run_pi.sh [fazetime_worker run args...]   e.g. --dry-run, --duration-s 900
set -euo pipefail
cd "$(dirname "$0")/.."
DATA="${FAZETIME_DATA:-$HOME/fazetime-data}"
mkdir -p "$DATA"
ENVFILE="$DATA/worker.env"
if [ -f "$ENVFILE" ]; then
  perm="$(stat -c %a "$ENVFILE")"
  if [ "$perm" != "600" ] && [ "$perm" != "400" ]; then echo "refusing: $ENVFILE must be chmod 600" >&2; exit 1; fi
  set -a; . "$ENVFILE"; set +a
fi
PIDFILE="$DATA/worker.pid"
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null && \
   tr '\0' ' ' < "/proc/$(cat "$PIDFILE")/cmdline" | grep -q "fazetime_worker run"; then
  echo "worker already running (pid $(cat "$PIDFILE"))" >&2; exit 1
fi
export FAZETIME_WORKER_DATA_DIR="${FAZETIME_WORKER_DATA_DIR:-$DATA/worker}"
export FAZETIME_STREAMLINK_BIN="${FAZETIME_STREAMLINK_BIN:-$PWD/.venv/bin/streamlink}"
export FAZETIME_ASR_MODELS_DIR="${FAZETIME_ASR_MODELS_DIR:-$PWD/models}"
echo "=== $(date -u +%FT%TZ) start: $*" >> "$DATA/worker.log"
setsid nohup .venv/bin/python -m fazetime_worker run "$@" >> "$DATA/worker.log" 2>&1 < /dev/null &
echo $! > "$PIDFILE"
echo "started pid $(cat "$PIDFILE"); log: $DATA/worker.log"
