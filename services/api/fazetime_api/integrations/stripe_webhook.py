"""Stripe webhook signature verification and minimal event parsing (P6-B). TEST MODE ONLY.

Scheme, verified against docs.stripe.com/webhooks ("Verify webhook signatures manually") on 2026-11-14:

* Header ``Stripe-Signature``: comma-separated ``key=value`` entries, e.g.
  ``t=1798765432,v1=<hex>,v1=<hex>,v0=<hex>,secret=whsec_****PzVt,destination=we_...,payload=a25aefc6``.
  Only ``t`` and ``v1`` are used. ``v0`` (fake sandbox scheme) and the unsigned debug entries
  (``secret``, ``destination``, ``payload``) are ignored, as are unknown entries; entry order and
  count are not assumed. Several ``v1`` entries appear while a signing secret is being rolled; at
  least one must match.
* ``signed_payload = t + "." + <raw request body bytes, unmodified>``.
* ``expected = HMAC-SHA256(key=<endpoint signing secret, the whole "whsec_..." string>, signed_payload)``,
  lowercase hex, compared in constant time against every ``v1`` value.
* Replay protection: reject when ``|now - t|`` exceeds the tolerance (Stripe default 300 s; 0 is
  forbidden because it disables the check). Stripe re-signs every retry with a fresh ``t``.

Never log the header (it carries a redacted secret hint) or the body (it can carry customer details).
Parsed events expose only the fields the fulfillment planner needs. Unknown event types parse to
``handled=False`` and must have no money effect. Live-mode events raise ``LivemodeEventRejected``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass

CHECKOUT_COMPLETED = "checkout.session.completed"
CHECKOUT_ASYNC_SUCCEEDED = "checkout.session.async_payment_succeeded"
CHECKOUT_ASYNC_FAILED = "checkout.session.async_payment_failed"
CHECKOUT_EXPIRED = "checkout.session.expired"
HANDLED_EVENT_TYPES = frozenset({CHECKOUT_COMPLETED, CHECKOUT_ASYNC_SUCCEEDED, CHECKOUT_ASYNC_FAILED, CHECKOUT_EXPIRED})

DEFAULT_TOLERANCE_S = 300
MAX_SIGNATURE_HEADER_CHARS = 4096
MAX_EVENT_BYTES = 256 * 1024
WEBHOOK_SECRET_ENV_NAME = "STRIPE_WEBHOOK_SECRET"

_TIMESTAMP_RE = re.compile(r"^[0-9]{1,12}$")
_EVENT_ID_RE = re.compile(r"^evt_[A-Za-z0-9]{1,250}$")
_EVENT_TYPE_RE = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+){1,6}$")
_SESSION_ID_RE = re.compile(r"^cs_(test|live)_[A-Za-z0-9]{1,250}$")
_PAYMENT_INTENT_RE = re.compile(r"^pi_[A-Za-z0-9]{1,250}$")
_CURRENCY_RE = re.compile(r"^[a-z]{3}$")
_SECRET_RE = re.compile(r"^whsec_[A-Za-z0-9+/=_-]{8,512}$")
_MAX_FIELD_CHARS = 512


class WebhookError(Exception):
    """Base error. ``code`` is a stable reason that is safe to log; messages never carry secrets or payloads."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class WebhookConfigError(WebhookError, ValueError):
    """The server's own configuration is unusable (for example a missing or malformed signing secret)."""


class SignatureVerificationError(WebhookError):
    """Codes: MALFORMED_HEADER, NO_V1_SIGNATURE, SIGNATURE_MISMATCH, TIMESTAMP_OUT_OF_TOLERANCE."""


class EventParseError(WebhookError):
    """A verified body is not a well-formed Stripe snapshot event of the expected shape."""


class LivemodeEventRejected(WebhookError):
    """A live-mode event or object. This demo accepts Stripe TEST mode only."""


@dataclass(frozen=True, slots=True)
class CheckoutSessionFacts:
    """The minimal, trusted-after-verification facts about one Checkout Session.

    Customer details (email, name, address) are deliberately not extracted.
    """

    session_id: str
    livemode: bool
    status: str | None  # open | complete | expired
    payment_status: str | None  # paid | unpaid | no_payment_required
    amount_total: int | None  # minor units
    currency: str | None  # lowercase ISO code
    topup_id: str | None  # metadata.topup_id
    client_reference_id: str | None
    payment_intent_id: str | None
    mode: str | None  # payment | setup | subscription

    @property
    def is_paid(self) -> bool:
        return self.status == "complete" and self.payment_status == "paid"


@dataclass(frozen=True, slots=True)
class StripeEvent:
    event_id: str
    type: str
    livemode: bool
    created: int
    api_version: str | None
    session: CheckoutSessionFacts | None  # None unless ``handled``
    payload_sha256: str  # store this, not the raw body

    @property
    def handled(self) -> bool:
        return self.type in HANDLED_EVENT_TYPES and self.session is not None


# ------------------------------------------------------------------------------------------------
# Signatures
# ------------------------------------------------------------------------------------------------
def require_webhook_secret(secret: object) -> str:
    """Validate a signing secret (dashboard or ``stripe listen``); both start with ``whsec_``."""
    if not isinstance(secret, str) or not _SECRET_RE.fullmatch(secret):
        raise WebhookConfigError("BAD_SECRET", "the webhook signing secret must be a whsec_... value")
    return secret


def compute_signature(secret: str, timestamp: int | str, raw_body: bytes) -> str:
    """Lowercase hex HMAC-SHA256 of ``f"{t}." + raw_body`` keyed by the whole ``whsec_`` secret."""
    signed = str(timestamp).encode("ascii") + b"." + bytes(raw_body)
    return hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()


def build_test_signature_header(raw_body: bytes, secret: str, timestamp: int) -> str:
    """Offline tests and clearly labelled simulations only. Real deliveries are signed by Stripe."""
    return f"t={int(timestamp)},v1={compute_signature(secret, int(timestamp), raw_body)}"


def _parse_signature_header(header: object) -> tuple[int, list[str]]:
    if not isinstance(header, str) or not header.strip():
        raise SignatureVerificationError("MALFORMED_HEADER", "missing Stripe-Signature header")
    if len(header) > MAX_SIGNATURE_HEADER_CHARS:
        raise SignatureVerificationError("MALFORMED_HEADER", "Stripe-Signature header is too long")
    timestamp: int | None = None
    v1: list[str] = []
    for item in header.split(","):
        key, sep, value = item.strip().partition("=")
        if not sep:
            continue  # unknown or empty entry: ignored, never trusted
        if key == "t":
            if timestamp is not None:
                raise SignatureVerificationError("MALFORMED_HEADER", "more than one timestamp")
            if not _TIMESTAMP_RE.fullmatch(value):
                raise SignatureVerificationError("MALFORMED_HEADER", "timestamp is not an integer")
            timestamp = int(value)
        elif key == "v1" and value:
            v1.append(value)
        # v0, secret, destination, payload and unknown schemes: ignored (downgrade protection)
    if timestamp is None:
        raise SignatureVerificationError("MALFORMED_HEADER", "no timestamp entry")
    if not v1:
        raise SignatureVerificationError("NO_V1_SIGNATURE", "no v1 signature entry")
    return timestamp, v1


def verify_signature(
    raw_body: bytes,
    header: str,
    secret: str,
    tolerance_s: int = DEFAULT_TOLERANCE_S,
    now: float | None = None,
) -> int:
    """Verify a delivery against the raw request bytes. Returns the signed timestamp.

    Raises SignatureVerificationError for a bad request and WebhookConfigError for a bad secret.
    Call this before reading any business field of the body.
    """
    if not isinstance(raw_body, (bytes, bytearray, memoryview)):
        raise TypeError("raw_body must be the raw request bytes, not parsed or decoded data")
    require_webhook_secret(secret)
    if isinstance(tolerance_s, bool) or not isinstance(tolerance_s, int) or tolerance_s <= 0:
        raise ValueError("tolerance_s must be a positive integer (0 would disable replay protection)")
    timestamp, candidates = _parse_signature_header(header)
    expected = compute_signature(secret, timestamp, bytes(raw_body)).encode("ascii")
    matched = False
    for candidate in candidates:  # every candidate is compared; no early exit
        if hmac.compare_digest(expected, candidate.encode("utf-8", "replace")):
            matched = True
    if not matched:
        raise SignatureVerificationError("SIGNATURE_MISMATCH", "no v1 signature matches this payload")
    current = time.time() if now is None else float(now)
    if abs(current - timestamp) > tolerance_s:
        raise SignatureVerificationError("TIMESTAMP_OUT_OF_TOLERANCE", f"signature timestamp is outside {tolerance_s} s")
    return timestamp


# ------------------------------------------------------------------------------------------------
# Parsing
# ------------------------------------------------------------------------------------------------
def _opt_str(obj: dict, key: str, *, error: type[WebhookError] = EventParseError) -> str | None:
    value = obj.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > _MAX_FIELD_CHARS:
        raise error("BAD_FIELD", f"{key} has an unexpected type or length")
    return value


def session_facts_from_object(obj: object) -> CheckoutSessionFacts:
    """Extract facts from a ``checkout.session`` object (webhook ``data.object`` or an API retrieve)."""
    if not isinstance(obj, dict) or obj.get("object") != "checkout.session":
        raise EventParseError("NOT_A_CHECKOUT_SESSION", "data.object is not a checkout.session")
    session_id = obj.get("id")
    if not isinstance(session_id, str) or not _SESSION_ID_RE.fullmatch(session_id):
        raise EventParseError("BAD_SESSION_ID", "checkout.session id is malformed")
    livemode = obj.get("livemode")
    if not isinstance(livemode, bool):
        raise EventParseError("BAD_LIVEMODE", "checkout.session livemode is not a boolean")
    if livemode or session_id.startswith("cs_live_"):
        raise LivemodeEventRejected("LIVEMODE_OBJECT", "live-mode Checkout Session refused (TEST mode only)")
    amount_total = obj.get("amount_total")
    if amount_total is not None and (type(amount_total) is not int or amount_total < 0):
        raise EventParseError("BAD_AMOUNT", "amount_total is not a non-negative integer")
    currency = _opt_str(obj, "currency")
    if currency is not None:
        currency = currency.lower()
        if not _CURRENCY_RE.fullmatch(currency):
            raise EventParseError("BAD_CURRENCY", "currency is not a three-letter code")
    metadata = obj.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise EventParseError("BAD_METADATA", "metadata is not an object")
    topup_id = (metadata or {}).get("topup_id")
    if topup_id is not None and (not isinstance(topup_id, str) or len(topup_id) > _MAX_FIELD_CHARS):
        raise EventParseError("BAD_METADATA", "metadata.topup_id is not a string")
    payment_intent = obj.get("payment_intent")
    if isinstance(payment_intent, dict):  # expanded object
        payment_intent = payment_intent.get("id")
    if payment_intent is not None and (
        not isinstance(payment_intent, str) or not _PAYMENT_INTENT_RE.fullmatch(payment_intent)
    ):
        raise EventParseError("BAD_PAYMENT_INTENT", "payment_intent is malformed")
    return CheckoutSessionFacts(
        session_id=session_id,
        livemode=False,
        status=_opt_str(obj, "status"),
        payment_status=_opt_str(obj, "payment_status"),
        amount_total=amount_total,
        currency=currency,
        topup_id=topup_id,
        client_reference_id=_opt_str(obj, "client_reference_id"),
        payment_intent_id=payment_intent,
        mode=_opt_str(obj, "mode"),
    )


def parse_event(raw_body: bytes) -> StripeEvent:
    """Parse an already verified snapshot event. Raises EventParseError or LivemodeEventRejected."""
    if not isinstance(raw_body, (bytes, bytearray, memoryview)):
        raise TypeError("raw_body must be the raw request bytes")
    raw = bytes(raw_body)
    if len(raw) > MAX_EVENT_BYTES:
        raise EventParseError("TOO_LARGE", f"event body exceeds {MAX_EVENT_BYTES} bytes")
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise EventParseError("INVALID_JSON", "event body is not UTF-8 JSON") from None
    if not isinstance(doc, dict) or doc.get("object") != "event":
        raise EventParseError("NOT_AN_EVENT", "body is not a Stripe snapshot event")
    event_id = doc.get("id")
    if not isinstance(event_id, str) or not _EVENT_ID_RE.fullmatch(event_id):
        raise EventParseError("BAD_EVENT_ID", "event id is malformed")
    event_type = doc.get("type")
    if not isinstance(event_type, str) or len(event_type) > 128 or not _EVENT_TYPE_RE.fullmatch(event_type):
        raise EventParseError("BAD_EVENT_TYPE", "event type is malformed")
    livemode = doc.get("livemode")
    if not isinstance(livemode, bool):
        raise EventParseError("BAD_LIVEMODE", "event livemode is not a boolean")
    if livemode:
        raise LivemodeEventRejected("LIVEMODE_EVENT", "live-mode event refused (TEST mode only)")
    created = doc.get("created")
    if type(created) is not int or created < 0:
        raise EventParseError("BAD_CREATED", "event created is not a non-negative integer")
    api_version = doc.get("api_version")
    api_version = api_version if isinstance(api_version, str) and len(api_version) <= 64 else None
    data = doc.get("data")
    obj = data.get("object") if isinstance(data, dict) else None
    if isinstance(obj, dict) and obj.get("livemode") is True:
        raise LivemodeEventRejected("LIVEMODE_OBJECT", "live-mode object refused (TEST mode only)")
    digest = hashlib.sha256(raw).hexdigest()
    if event_type not in HANDLED_EVENT_TYPES:
        return StripeEvent(event_id, event_type, False, created, api_version, None, digest)
    return StripeEvent(event_id, event_type, False, created, api_version, session_facts_from_object(obj), digest)


def construct_event(
    raw_body: bytes,
    header: str,
    secret: str,
    tolerance_s: int = DEFAULT_TOLERANCE_S,
    now: float | None = None,
) -> StripeEvent:
    """verify_signature() then parse_event(), in that order."""
    verify_signature(raw_body, header, secret, tolerance_s=tolerance_s, now=now)
    return parse_event(raw_body)
