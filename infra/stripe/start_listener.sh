#!/usr/bin/env bash
# Start the Stripe TEST-mode webhook listener on the laptop (no-op if running).
# Forwards checkout.session.* events to the Pi API. Key comes from .env.local (test keys only).
# The log contains the webhook signing secret: it lives in a 0700 dir with 0600 perms; never print it.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STATE="$HOME/.local/state/fazetime"; LOG="$STATE/stripe-listen.log"
TARGET="${FAZETIME_WEBHOOK_TARGET:-http://fazetime:8000/v1/webhooks/stripe}"
mkdir -p "$STATE"; chmod 700 "$STATE"
if pgrep -f "[s]tripe listen --device-name fazetime-api" >/dev/null; then echo "listener already running"; exit 0; fi
K=$(grep -E '^STRIPE_SECRET_KEY=' "$REPO/.env.local" | head -1 | cut -d= -f2- | tr -d '"'"'"'\r ')
case "$K" in sk_test_*|rk_test_*) ;; *) echo "refusing: STRIPE_SECRET_KEY is not a test key"; exit 1;; esac
umask 077
STRIPE_API_KEY="$K" setsid nohup "$HOME/.local/bin/stripe" listen --device-name fazetime-api \
  --events checkout.session.completed,checkout.session.async_payment_succeeded,checkout.session.async_payment_failed,checkout.session.expired \
  --forward-to "$TARGET" > "$LOG" 2>&1 < /dev/null &
unset K
for i in $(seq 1 15); do grep -q "Ready" "$LOG" 2>/dev/null && { echo "listener ready -> $TARGET"; exit 0; }; sleep 1; done
echo "listener started but not ready yet; check $LOG privately"
