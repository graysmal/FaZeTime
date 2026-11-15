#!/usr/bin/env bash
# TEST_FIXTURE source (NOT Twitch; never Twitch evidence). Writes MPEG-TS to stdout at real-time rate:
# part 1 (PART1_S, 440 Hz tone + test pattern), a delivery stall (STALL_S), then part 2 (PART2_S, 880 Hz)
# whose timestamps jump forward by JUMP_S (kept below FFmpeg's 10 s TS discontinuity correction).
set -e
P1="${PART1_S:-12}"; P2="${PART2_S:-10}"; STALL="${STALL_S:-3}"; JUMP="${JUMP_S:-5}"
gen() { ffmpeg -hide_banner -loglevel error -re -f lavfi -i "testsrc2=size=854x480:rate=30" \
  -f lavfi -i "sine=frequency=$1:sample_rate=48000" -t "$2" -c:v libx264 -preset ultrafast -g 60 \
  -c:a aac -output_ts_offset "$3" -f mpegts -; }
gen 440 "$P1" 0
sleep "$STALL"
gen 880 "$P2" "$(echo "$P1 + $JUMP" | bc)"
