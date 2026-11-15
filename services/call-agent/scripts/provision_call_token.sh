#!/usr/bin/env bash
# Mint this line's CALL_WORKER token on the Pi (CONTRACTS 9.21) and store it in .env.local
# as FAZETIME_CALL_WORKER_TOKEN. The token is never printed or passed on a command line.
# Usage: scripts/provision_call_token.sh [label]
set -euo pipefail
HOST="${FAZETIME_PI:-fazetime@fazetime}"
cd "$(dirname "$0")/.."
ssh "$HOST" "cd ~/fazetime/services/api && FAZETIME_DATA_DIR=~/fazetime-data .venv/bin/python -m fazetime_api issue-call-worker-token --label ${1:-call-agent}" \
  | python3 -c '
import re, sys
from pathlib import Path
m = re.search(r"fzk_[A-Za-z0-9_-]{20,}", sys.stdin.read())
if not m:
    sys.exit("no token found in the CLI output")
p = Path(".env.local")
lines = [l for l in p.read_text().splitlines() if not l.startswith("FAZETIME_CALL_WORKER_TOKEN=")]
lines.append("FAZETIME_CALL_WORKER_TOKEN=" + m.group(0))
p.write_text("\n".join(lines) + "\n")
p.chmod(0o600)
print("stored FAZETIME_CALL_WORKER_TOKEN in .env.local (not printed)")
'
