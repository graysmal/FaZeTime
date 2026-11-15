#!/usr/bin/env bash
# TOOLCHAIN_SMOKE: one Streamlink -> FFmpeg path, fixed duration, public channel.
# Produces out/smoke/<channel>/audio.wav (16 kHz mono s16le) and one JPEG every 2 s.
# Usage: ./smoke_capture.sh <channel> <quality> <seconds>
set -euo pipefail
cd "$(dirname "$0")"
CH="${1:?channel}"; Q="${2:-480p30}"; DUR="${3:-180}"
OUT="out/smoke/$CH"; mkdir -p "$OUT/frames"; rm -f "$OUT"/frames/*.jpg "$OUT"/audio.wav
cat /proc/loadavg > "$OUT/loadavg_start.txt"
T0=$(.venv/bin/python -I -c 'import time;print(time.monotonic_ns())')
date -u +%FT%T.%NZ > "$OUT/launch_utc.txt"
set +e
timeout $((DUR + 90)) /usr/bin/time -v -o "$OUT/streamlink.time" \
  .venv/bin/streamlink --loglevel debug \
    --logformat "[{asctime}][{name}][{levelname}] {message}" --logdateformat "%H:%M:%S.%f" \
    --stdout "https://twitch.tv/$CH" "$Q" 2> "$OUT/streamlink.log" \
| .venv/bin/python -I tools/pipe_meter.py "$OUT/pipe_meter.json" "$T0" \
| /usr/bin/time -v -o "$OUT/ffmpeg.time" \
  ffmpeg -hide_banner -nostdin -loglevel level+info -i pipe:0 \
    -map 0:a:0 -t "$DUR" -ac 1 -ar 16000 -c:a pcm_s16le -y "$OUT/audio.wav" \
    -map 0:v:0 -t "$DUR" -vf fps=1/2 -q:v 5 -y "$OUT/frames/f_%04d.jpg" 2> "$OUT/ffmpeg.log"
echo "pipestatus=${PIPESTATUS[*]}" > "$OUT/pipestatus.txt"
set -e
cat /proc/loadavg > "$OUT/loadavg_end.txt"
date -u +%FT%T.%NZ > "$OUT/end_utc.txt"
