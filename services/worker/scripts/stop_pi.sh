#!/usr/bin/env bash
# Graceful stop: SIGTERM -> capture stops, final STOPPED heartbeat, uplink drained (<= ~30 s), then exit.
set -euo pipefail
DATA="${FAZETIME_DATA:-$HOME/fazetime-data}"
PIDFILE="$DATA/worker.pid"
[ -f "$PIDFILE" ] || { echo "no pid file"; exit 0; }
PID="$(cat "$PIDFILE")"
if kill -0 "$PID" 2>/dev/null && tr '\0' ' ' < "/proc/$PID/cmdline" | grep -q "fazetime_worker run"; then
  kill -TERM "$PID"
  for _ in $(seq 1 60); do kill -0 "$PID" 2>/dev/null || break; sleep 1; done
  kill -0 "$PID" 2>/dev/null && { echo "still running after 60 s; sending SIGKILL"; kill -KILL "$PID"; }
fi
rm -f "$PIDFILE"
echo "stopped"
