"""stdin -> stdout byte pump that records first-byte latency and stall gaps.

Used only by smoke_capture.sh (TOOLCHAIN_SMOKE). Writes a small JSON summary
to the path given as argv[1]. argv[2] is the launch monotonic time in ns of
the pipeline (so first-byte latency includes Streamlink startup).
"""
import json
import os
import sys
import time

out_path = sys.argv[1]
t_launch = int(sys.argv[2]) if len(sys.argv) > 2 else time.monotonic_ns()
fin = sys.stdin.buffer.raw
fout = sys.stdout.buffer.raw
first = None
last = None
total = 0
max_gap_ns = 0
gaps_over_2s = []
try:
    while True:
        b = fin.read(65536)
        now = time.monotonic_ns()
        if not b:
            break
        if first is None:
            first = now
        elif now - last > max_gap_ns:
            max_gap_ns = now - last
        if last is not None and now - last > 2_000_000_000:
            gaps_over_2s.append({"at_s": round((now - t_launch) / 1e9, 3), "gap_s": round((now - last) / 1e9, 3)})
        last = now
        total += len(b)
        mv = memoryview(b)
        while mv:
            n = fout.write(mv)
            mv = mv[n:]
except BrokenPipeError:
    pass
finally:
    end = time.monotonic_ns()
    with open(out_path, "w") as f:
        json.dump({
            "first_byte_after_launch_s": None if first is None else round((first - t_launch) / 1e9, 3),
            "bytes": total,
            "active_s": None if first is None else round(((last or first) - first) / 1e9, 3),
            "mean_input_kbit_s": None if not first or last == first else round(total * 8 / ((last - first) / 1e9) / 1000, 1),
            "max_inter_read_gap_s": round(max_gap_ns / 1e9, 3),
            "gaps_over_2s": gaps_over_2s[:50],
            "ended_after_launch_s": round((end - t_launch) / 1e9, 3),
        }, f, indent=1)
