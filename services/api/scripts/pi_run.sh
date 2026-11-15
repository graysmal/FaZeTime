#!/usr/bin/env bash
# FaZeTime API on the Pi: start | stop | status | restart.
# Binds ONLY to this host's Tailscale IPv4 (100.x) — never 0.0.0.0 on venue Wi-Fi. No sudo.
# Data (SQLite DB + bounded evidence dir) lives in FAZETIME_DATA_DIR (default ~/fazetime-data).
set -euo pipefail

cmd="${1:-status}"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${FAZETIME_DATA_DIR:-$HOME/fazetime-data}"
PORT="${FAZETIME_PORT:-8000}"
PID_FILE="$DATA_DIR/api.pid"
LOG_FILE="$DATA_DIR/api.log"
UV="${UV:-$HOME/.local/bin/uv}"
# WebSocket allowlist: twitch.tv + the pinned extension ID (exact match; CORS gets only the extension origin).
ALLOWED_ORIGINS="${FAZETIME_ALLOWED_ORIGINS:-https://www.twitch.tv,chrome-extension://hodaaffdhncidmaccebmionoljljfefe}"
# Optional operator UI build (apps/operator, Vite base '/operator/'), served same-origin at /operator/.
OPERATOR_DIST="${FAZETIME_OPERATOR_DIST:-$HOME/fazetime/apps/operator/dist}"

tailnet_ip() { tailscale ip -4 2>/dev/null | head -n1; }
running() { [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; }

start() {
  if running; then echo "already running (pid $(cat "$PID_FILE"))"; return 0; fi
  local host="${FAZETIME_HOST:-$(tailnet_ip)}"
  case "$host" in
    100.*) ;;
    *) echo "refusing to start: no Tailscale IPv4 (got '${host}')" >&2; return 2 ;;
  esac
  mkdir -p "$DATA_DIR/evidence"
  cd "$APP_DIR"
  local py="$APP_DIR/.venv/bin/python"
  [ -x "$py" ] || { echo "missing $py; run: $UV sync --frozen" >&2; return 2; }
  echo "$(date -u +%FT%TZ) starting on ${host}:${PORT}" >>"$LOG_FILE"
  local dist_env=()
  [ -f "$OPERATOR_DIST/index.html" ] && dist_env=(FAZETIME_OPERATOR_DIST="$OPERATOR_DIST")
  env FAZETIME_DATA_DIR="$DATA_DIR" FAZETIME_HOST="$host" FAZETIME_PORT="$PORT" \
    FAZETIME_ALLOWED_ORIGINS="$ALLOWED_ORIGINS" "${dist_env[@]}" \
    setsid nohup "$py" -m fazetime_api serve >>"$LOG_FILE" 2>&1 </dev/null &
  echo $! >"$PID_FILE"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    sleep 1
    if curl -fsS "http://${host}:${PORT}/healthz" >/dev/null 2>&1; then
      echo "started pid $(cat "$PID_FILE") at http://${host}:${PORT} (log ${LOG_FILE})"
      return 0
    fi
    running || break
  done
  echo "failed to start; last log lines:" >&2
  tail -n 20 "$LOG_FILE" >&2
  return 1
}

stop() {
  if ! running; then echo "not running"; rm -f "$PID_FILE"; return 0; fi
  local pid
  pid="$(cat "$PID_FILE")"
  kill -TERM -- "-${pid}" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true  # whole process group
  for _ in $(seq 1 20); do
    kill -0 "$pid" 2>/dev/null || { rm -f "$PID_FILE"; echo "stopped pid ${pid}"; return 0; }
    sleep 0.5
  done
  echo "pid ${pid} did not exit after 10 s; not force-killing (check ${LOG_FILE})" >&2
  return 1
}

status() {
  local host="${FAZETIME_HOST:-$(tailnet_ip)}"
  if running; then
    echo "running pid $(cat "$PID_FILE")"
    ss -ltn 2>/dev/null | grep ":${PORT} " || true
    curl -fsS "http://${host}:${PORT}/healthz" && echo
  else
    echo "not running"
    return 3
  fi
}

case "$cmd" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  restart) stop && start ;;
  *) echo "usage: $0 start|stop|status|restart" >&2; exit 64 ;;
esac
