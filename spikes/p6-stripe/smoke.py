#!/usr/bin/env python3
"""P6 Stripe TEST-mode smoke run (spike; not application code). No payment is completed.

REST calls through the adapter (hard cap 5, normally 3):
  1. create ONE Checkout Session for 500 cents (placeholder example.com return URLs, 35 min expiry)
  2. retrieve it; require livemode=false, status=open, payment_status=unpaid
  3. expire it while `stripe listen` is forwarding, to obtain ONE genuinely Stripe-signed
     checkout.session.expired event. No card is entered and nothing is charged.

`stripe listen` gets the key through the STRIPE_API_KEY environment variable, never through argv,
so it does not appear in the process list. Its signing secret is held in memory only. Every line of
output passes through redaction: no key, no whsec_ secret, no Checkout URL, and only short id
prefixes. The local receiver verifies the forwarded event with the adapter's verify_signature() and
parse_event(), then runs the pure planner against a synthetic in-memory record. There is no database
and no ledger.

Usage: python3 -I spikes/p6-stripe/smoke.py [--skip-cli]
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import platform
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "services" / "api"))

from fazetime_api.integrations import stripe_client as sc  # noqa: E402
from fazetime_api.integrations import stripe_fulfillment as sf  # noqa: E402
from fazetime_api.integrations import stripe_webhook as sw  # noqa: E402

STRIPE_CLI = os.path.expanduser("~/.local/bin/stripe")
DEVICE_NAME = "fazetime-smoke"
MAX_REST_CALLS = 3  # task budget is 5 REST calls in total; run 1 spent 1 (HTTP 400, Managed Payments)
_ID_RE = re.compile(r"\b(cs_test|cs_live|evt|pi|we|acct|ch|py)_([A-Za-z0-9]{4})[A-Za-z0-9]*")
_SECRET_RE = re.compile(r"whsec_[A-Za-z0-9+/=_-]+")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def safe(text: object) -> str:
    """Redact secrets and Checkout URLs, and shorten object ids to a 4-character prefix."""
    out = sc.redact(_ANSI_RE.sub("", str(text)))
    return _ID_RE.sub(lambda m: f"{m.group(1)}_{m.group(2)}...", out)


def say(label: str, **fields) -> None:
    body = " ".join(f"{k}={safe(v)}" for k, v in fields.items())
    print(f"[smoke] {label}: {body}".rstrip(), flush=True)


class CountingTransport:
    def __init__(self, inner):
        self.inner = inner
        self.calls: list[str] = []

    def __call__(self, method, path, headers, body, timeout):
        if len(self.calls) >= MAX_REST_CALLS:
            raise RuntimeError("smoke REST call budget exhausted")
        self.calls.append(f"{method} {safe(path)}")
        return self.inner(method, path, headers, body, timeout)


class Receiver(http.server.ThreadingHTTPServer):
    secret: str | None = None
    record: sf.TopupRecord | None = None
    results: "queue.Queue[dict]"
    last_raw: bytes | None = None
    last_header: str | None = None


class Handler(http.server.BaseHTTPRequestHandler):
    server: Receiver

    def do_POST(self):  # noqa: N802 (stdlib name)
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > sw.MAX_EVENT_BYTES:
            self.send_response(413)
            self.end_headers()
            return
        raw = self.rfile.read(length)
        header = self.headers.get("Stripe-Signature", "")
        result: dict = {"received_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        code = 400
        try:
            if not self.server.secret:
                raise sw.WebhookConfigError("BAD_SECRET", "secret not captured yet")
            ts = sw.verify_signature(raw, header, self.server.secret)
            event = sw.parse_event(raw)
            rec = self.server.record
            match = rec if (event.session is not None and event.session.topup_id == rec.topup_id) else None
            plan = sf.plan_fulfillment(match, event)
            s = event.session
            result.update(
                verified=True, signed_age_s=round(time.time() - ts, 1), event_type=event.type,
                event_id=event.event_id, livemode=event.livemode, event_api_version=event.api_version,
                handled=event.handled, session_id=s.session_id if s else None,
                session_status=s.status if s else None, payment_status=s.payment_status if s else None,
                amount_total=s.amount_total if s else None, currency=s.currency if s else None,
                topup_matches=match is not None, plan_action=plan.action.value, plan_reason=plan.reason,
                plan_moves_money=plan.moves_money, v1_entries=header.count("v1="),
            )
            self.server.last_raw, self.server.last_header = raw, header
            code = 200
        except sw.WebhookError as exc:
            result.update(verified=False, error=exc.code)
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"received":true}' if code == 200 else b'{"received":false}')
        self.server.results.put(result)

    def log_message(self, *args):  # keep the stdlib server quiet (it would print paths and addresses)
        pass


def cli_env(key: str) -> dict:
    env = dict(os.environ)
    env["STRIPE_API_KEY"] = key  # env, not argv: invisible in `ps`
    return env


def run_cli_phase(client: sc.StripeTestClient, key: str, session_id: str, record: sf.TopupRecord) -> dict:
    out: dict = {}
    version = subprocess.run([STRIPE_CLI, "version"], capture_output=True, text=True, timeout=20)
    out["cli_version"] = (version.stdout.strip().splitlines() or ["?"])[0]
    say("cli", version=out["cli_version"])

    printed = subprocess.run(
        [STRIPE_CLI, "listen", "--print-secret", "--skip-update", "--device-name", DEVICE_NAME, "--color", "off"],
        env=cli_env(key), capture_output=True, text=True, timeout=60,
    )
    found = _SECRET_RE.search(printed.stdout or "")
    printed_secret = found.group(0) if found else None
    say("cli --print-secret", exit=printed.returncode, issued_secret=bool(printed_secret), secret="whsec_[REDACTED]")

    server = Receiver(("127.0.0.1", 0), Handler)
    server.results = queue.Queue()
    server.record = record
    server.secret = printed_secret
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    cmd = [STRIPE_CLI, "listen", "--skip-update", "--device-name", DEVICE_NAME, "--color", "off",
           "--events", ",".join(sorted(sw.HANDLED_EVENT_TYPES)),
           "--forward-to", f"http://127.0.0.1:{port}/webhook"]
    proc = subprocess.Popen(cmd, env=cli_env(key), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            bufsize=1)
    ready = threading.Event()
    lines: list[str] = []
    holder: dict = {}

    def pump():
        for line in proc.stdout:  # type: ignore[union-attr]
            m = _SECRET_RE.search(line)
            if m and "secret" not in holder:
                holder["secret"] = m.group(0)
            v = re.search(r"API [Vv]ersion \[([^\]]+)\]", line)
            if v:
                holder["listener_api_version"] = v.group(1)
            lines.append(safe(line.rstrip()))
            if "Ready!" in line:
                ready.set()

    threading.Thread(target=pump, daemon=True).start()
    started = time.monotonic()
    try:
        if not ready.wait(60):
            out["listener_ready"] = False
            say("cli listen", ready=False, note="no Ready line within 60 s")
            return out
        out["listener_ready"] = True
        out["listener_ready_s"] = round(time.monotonic() - started, 1)
        out["listener_api_version"] = holder.get("listener_api_version")
        listener_secret = holder.get("secret")
        out["listener_issued_secret"] = bool(listener_secret)
        out["print_secret_matches_listener"] = bool(listener_secret) and listener_secret == printed_secret
        if listener_secret:
            server.secret = listener_secret  # the listener's own secret is authoritative for its deliveries
        say("cli listen", ready=True, after_s=out["listener_ready_s"], listener_api_version=out["listener_api_version"],
            issued_secret=out["listener_issued_secret"], secret="whsec_[REDACTED]",
            print_secret_matches_listener=out["print_secret_matches_listener"])
        time.sleep(1.0)

        expired = client.expire_session(session_id, idempotency_key=f"fazetime:smoke-expire:{record.topup_id}")
        say("rest expire", session=expired.session_id, status=expired.status, payment_status=expired.payment_status,
            livemode=expired.livemode, request_id=expired.request_id)
        try:
            result = server.results.get(timeout=60)
        except queue.Empty:
            out["event_received"] = False
            say("webhook", received=False, note="no forwarded event within 60 s")
            return out
        out["event_received"] = True
        out["event"] = result
        say("webhook", **{k: v for k, v in result.items() if k != "received_at_utc"})

        if server.last_raw is not None and server.last_header is not None and server.secret:
            raw, header, secret = server.last_raw, server.last_header, server.secret
            tampered = re.sub(rb'"amount_total":\s*500\b', b'"amount_total": 50000', raw, count=1)
            checks = {"tamper_applied": tampered != raw}
            for name, args in {
                "tampered_amount": (tampered, header, secret, sw.DEFAULT_TOLERANCE_S, None),
                "whitespace_appended": (raw + b"\n", header, secret, sw.DEFAULT_TOLERANCE_S, None),
                "stale_by_301s": (raw, header, secret, sw.DEFAULT_TOLERANCE_S,
                                  int(re.search(r"t=(\d+)", header).group(1)) + 301),
                "wrong_secret": (raw, header, "whsec_" + "0" * 32, sw.DEFAULT_TOLERANCE_S, None),
            }.items():
                try:
                    sw.verify_signature(args[0], args[1], args[2], tolerance_s=args[3], now=args[4])
                    checks[name] = "ACCEPTED (unexpected)"
                except sw.SignatureVerificationError as exc:
                    checks[name] = f"rejected:{exc.code}"
            out["negative_checks_on_real_delivery"] = checks
            say("verify negatives (real delivery, offline)", **checks)
        return out
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        out["listener_exit_code"] = proc.returncode
        out["listener_log"] = [ln for ln in lines if ln.strip()][:12]
        server.shutdown()
        server.server_close()
        for ln in out["listener_log"]:
            print(f"[stripe-cli] {ln}", flush=True)
        say("cli listen", stopped=True, exit_code=proc.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-cli", action="store_true", help="skip stripe listen and the expire call")
    args = parser.parse_args()

    say("start", utc=datetime.now(timezone.utc).isoformat(timespec="seconds"), python=platform.python_version(),
        pinned_stripe_version=sc.STRIPE_API_VERSION)
    try:
        key = sc.load_test_secret_key(env_file=REPO / ".env.local")
    except sc.StripeConfigError as exc:
        say("refused", reason=str(exc))
        return 2
    try:  # the refusal path, offline
        sc.StripeTestClient("sk_live_" + "0" * 24, transport=lambda *a: None)
        say("live key guard", result="ACCEPTED (unexpected)")
    except sc.StripeConfigError:
        say("live key guard", result="refused locally")

    transport = CountingTransport(sc.https_transport())
    client = sc.StripeTestClient(key, transport=transport, max_network_retries=0)
    say("client", key_kind=client.key_kind, mode="TEST")

    topup_id = "top_" + uuid.uuid4().hex  # smoke placeholder; no database row exists
    idem = f"fazetime:smoke:{topup_id}"
    success = f"https://example.com/fazetime-test/success?topup_id={topup_id}"
    cancel = f"https://example.com/fazetime-test/cancel?topup_id={topup_id}"
    expires_at = int(time.time()) + 35 * 60

    created = client.create_checkout_session(500, topup_id, success, cancel, idem, expires_at=expires_at)
    say("rest create", session=created.session_id, status=created.status, payment_status=created.payment_status,
        livemode=created.livemode, amount_total=created.facts.amount_total, currency=created.facts.currency,
        payment_method_types=",".join(created.payment_method_types), url_host=created.url_host,
        expires_in_s=(created.expires_at or 0) - int(time.time()), request_id=created.request_id,
        stripe_version_header=created.stripe_version, idempotent_replayed=created.idempotent_replayed)

    fetched = client.retrieve_session(created.session_id)
    assert fetched.livemode is False, "livemode must be false"
    assert fetched.payment_status == "unpaid" and fetched.status == "open", "session must be open and unpaid"
    assert fetched.facts.topup_id == topup_id and fetched.facts.amount_total == 500
    say("rest retrieve", session=fetched.session_id, status=fetched.status, payment_status=fetched.payment_status,
        livemode=fetched.livemode, topup_metadata_matches=fetched.facts.topup_id == topup_id,
        request_id=fetched.request_id, stripe_version_header=fetched.stripe_version)

    before = len(transport.calls)
    try:  # the local idempotency guard, offline
        client.create_checkout_session(1_000, topup_id, success, cancel, idem, expires_at=expires_at)
        say("idempotency guard", result="ACCEPTED (unexpected)")
    except sc.StripeIdempotencyConflict:
        say("idempotency guard", result="changed amount under the same key refused locally",
            network_calls=len(transport.calls) - before)

    record = sf.TopupRecord(topup_id=topup_id, user_id="usr_" + "0" * 32, run_id="run_" + "0" * 32,
                            amount_minor=500, currency="usd", status="PENDING",
                            stripe_session_id=created.session_id, run_state="ACTIVE")
    recon = sf.plan_reconciliation(record, fetched.facts, requester_user_id=record.user_id)
    say("planner on retrieved session", action=recon.action.value, reason=recon.reason, moves_money=recon.moves_money)

    summary: dict = {}
    if args.skip_cli or not os.path.isfile(STRIPE_CLI):
        say("cli", skipped=True)
    else:
        summary = run_cli_phase(client, key, created.session_id, record)
    say("done", rest_calls=len(transport.calls), calls=" | ".join(transport.calls),
        utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        event_verified=bool(summary.get("event", {}).get("verified")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
