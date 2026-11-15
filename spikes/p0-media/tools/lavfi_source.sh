#!/usr/bin/env bash
# OFFLINE TEST SOURCE (not Twitch): two synthetic MPEG-TS parts at real-time rate,
# the second with a +5 s timestamp jump (below FFmpeg's 10 s TS discontinuity
# correction) and a 7 s delivery stall between them.
set -e
gen() { ffmpeg -hide_banner -loglevel error -re -f lavfi -i "testsrc2=size=640x360:rate=30" \
  -f lavfi -i "sine=frequency=$1:sample_rate=48000" -t "$2" -c:v libx264 -preset ultrafast -g 30 \
  -c:a aac -output_ts_offset "$3" -f mpegts -; }
gen 440 10 0
sleep "${STALL_S:-7}"
gen 880 10 15
