#!/bin/bash
# Start the Vultr budget guard once (no-op if already running). Used by crontab @reboot too.
if pgrep -f "[b]udget_guard.py --env-file" >/dev/null; then echo "guard already running"; exit 0; fi
setsid nohup python3 -I "$HOME/fazetime/infra/vultr/budget_guard.py" --env-file "$HOME/fazetime-data/vultr.env" --log "$HOME/fazetime-data/vultr-guard.log" run --interval 300 >/dev/null 2>&1 < /dev/null &
echo "guard started"
