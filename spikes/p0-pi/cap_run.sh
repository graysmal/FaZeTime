#!/usr/bin/env bash
# Pi capture-cost run: capture_spike.py (Streamlink -> ffmpeg CLI, 4 s audio chunks + 1 frame / 2 s) with a
# 2 s temp/throttle/clock monitor; optionally a concurrent pi_asr_bench.py run started once audio is LIVE.
# Usage (on the Pi, from ~/fazetime-spike): bash cap_run.sh <label> <channel> <capture_s> [bench_runs]
# Spike only. Public channel, anonymous, no flags. Media lands in out/cap_<label>/{audio,frames}; delete after.
set -u
cd "$HOME/fazetime-spike" || exit 1
L=$1; CH=$2; D=$3; RUNS=${4:-}
OUT="out/cap_$L"
rm -rf "$OUT"; mkdir -p "$OUT"
uvc() { dmesg | grep -c "Undervoltage detected"; }
mon() { while :; do echo "$(date -u +%H:%M:%S) $(vcgencmd measure_temp) $(vcgencmd get_throttled) arm_hz=$(vcgencmd measure_clock arm | cut -d= -f2) load1=$(cut -d' ' -f1 /proc/loadavg)"; sleep 2; done; }
mon > "$OUT/mon.log" 2>&1 & MON=$!
echo "before $(date -u +%H:%M:%SZ) $(vcgencmd measure_temp) $(vcgencmd get_throttled) undervoltage_count=$(uvc)"
.venv/bin/python -I capture_spike.py --channel "$CH" --quality 480p30 --duration-s "$D" --out "$OUT" \
  > "$OUT/capture.stdout" 2>&1 & CAP=$!
if [ -n "$RUNS" ]; then
  for _ in $(seq 1 120); do grep -q '"AUDIO_CHUNK"' "$OUT/timeline.jsonl" 2>/dev/null && break; sleep 0.5; done
  echo "capture LIVE at $(date -u +%H:%M:%SZ); starting bench: $RUNS"
  .venv/bin/python -I pi_asr_bench.py --wav out/sample.wav --runs "$RUNS" --models-dir "$HOME/fazetime-spike/models" \
    --out "$OUT/bench.json" > "$OUT/bench.log" 2>&1
  echo "bench done $(date -u +%H:%M:%SZ)"; tail -3 "$OUT/bench.log"
  if grep -q '"stopped"' "$OUT/bench.json"; then echo "bench stopped on limit -> stopping capture"; kill -TERM $CAP; fi
fi
wait $CAP; echo "capture rc=$?"
kill $MON 2>/dev/null
echo "after $(date -u +%H:%M:%SZ) $(vcgencmd measure_temp) $(vcgencmd get_throttled) undervoltage_count=$(uvc)"
.venv/bin/python -I tools/check_timeline.py "$OUT/timeline.jsonl" > "$OUT/check.json"; echo "check rc=$?"
