#!/usr/bin/env bash
# Terminal A: run the FaZeTime call agent against the LiveKit project in .env.local.
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python agent.py start
