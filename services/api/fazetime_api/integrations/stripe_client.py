"""Stripe TEST-mode Checkout adapter (P6-A). Stdlib only, no database, no money authority.

Verified against docs.stripe.com on 2026-11-14:

* ``STRIPE_API_VERSION = "2026-10-28.endive"`` is the newest GA version in the changelog and in the
  API reference examples. It is pinned with the ``Stripe-Version`` request header, so the account's
  default version never changes request semantics. Response objects come back in this version.
  Webhook payloads do NOT follow this header: they use the listener/endpoint version (``stripe
  listen`` uses the account default unless ``--latest``). The parser reads only stable fields.
* ``2026-09-30.endive`` removed ``payment_method_types`` from Checkout Session create (passing it is a
  400). "Card only" is therefore ``allowed_payment_method_types[]=card``, a filter on the dynamically
  eligible methods. The created session's read-only ``payment_method_types`` is checked to be
  exactly ``["card"]``.
* MEASURED on the team's test account (smoke run, 2026-11-15 04:12Z): Managed Payments (Stripe's
  merchant-of-record product) is enabled by default there, and it rejects
  ``allowed_payment_method_types`` with HTTP 400. Each request therefore sends
  ``managed_payments[enabled]=false``, the documented per-request opt-out. This is a request
  parameter, not an account-settings change, and keeps the demo a plain test card payment.
* ``ui_mode`` defaults to ``hosted_page`` (Stripe-hosted Checkout, so card entry happens only on
  Stripe's page). ``expires_at`` may be 30 min to 24 h after creation (default 24 h).
* Idempotency keys are at most 255 characters and are pruned after at least 24 h. Reusing a key
  with different parameters is an ``idempotency_error``. This client also refuses such reuse
  locally, before any network call. The durable guard is the backend's topups row, which stores the
  key and ``checkout_request_fingerprint``.

The secret key is used only in the ``Authorization`` header. It is never logged, put in a URL, or
included in ``repr``. Only ``sk_test_`` or ``rk_test_`` keys are accepted, and any live-mode object
in a response is refused.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import logging
import os
import re
import ssl
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable, Mapping
from urllib.parse import urlencode, urlsplit

from ..config import Limits
from .stripe_webhook import CheckoutSessionFacts, EventParseError, LivemodeEventRejected, session_facts_from_object

log = logging.getLogger("fazetime.integrations.stripe")

STRIPE_API_HOST = "api.stripe.com"
STRIPE_API_VERSION = "2026-10-28.endive"
CHECKOUT_CURRENCY = "usd"
CHECKOUT_PRODUCT_NAME = "FaZeTime demo credits (TEST)"
CHECKOUT_PAYMENT_METHOD = "card"
SECRET_KEY_ENV_NAME = "STRIPE_SECRET_KEY"
TEST_KEY_PREFIXES = ("sk_test_", "rk_test_")
USER_AGENT = "fazetime-demo-stdlib/0.1 (test-mode)"
DEFAULT_TIMEOUT_S = 10.0
MAX_RESPONSE_BYTES = 1 << 20
CHECKOUT_MIN_EXPIRY_S = 30 * 60
CHECKOUT_MAX_EXPIRY_S = 24 * 3600

_TOPUP_ID_RE = re.compile(r"^[a-z]{2,5}_[0-9a-f]{32}$")  # proposed: top_<32 hex> (CONTRACTS §9.1 style)
_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9:_.\-]{8,255}$")
_TEST_SESSION_ID_RE = re.compile(r"^cs_test_[A-Za-z0-9]{1,250}$")
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_REDACTIONS = (
    (re.compile(r"\b(sk|rk|pk)_(test|live)_[A-Za-z0-9]+"), r"\1_\2_[REDACTED]"),
    (re.compile(r"whsec_[A-Za-z0-9+/=_-]+"), "whsec_[REDACTED]"),
    (re.compile(r"https://checkout\.stripe\.com/\S+"), "https://checkout.stripe.com/[REDACTED]"),
    (re.compile(r"https://dashboard\.stripe\.com/\S+"), "https://dashboard.stripe.com/[REDACTED]"),
    (re.compile(r"\bacct_[A-Za-z0-9]+"), "acct_[REDACTED]"),
)


def redact(text: object) -> str:
    """Strip keys, signing secrets, Checkout/Dashboard URLs and account ids from text bound for logs."""
    out = str(text)
    for pattern, replacement in _REDACTIONS:
        out = pattern.sub(replacement, out)
    return out


# ------------------------------------------------------------------------------------------------
# Errors. Suggested mapping to CONTRACTS §9.10 is in each docstring.
# ------------------------------------------------------------------------------------------------
class StripeError(Exception):
    code = "STRIPE_ERROR"
    default_retryable = False

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        request_id: str | None = None,
        stripe_type: str | None = None,
        stripe_code: str | None = None,
        retryable: bool | None = None,
        outcome_unknown: bool = False,
    ) -> None:
        super().__init__(redact(message))
        self.http_status = http_status
        self.request_id = request_id
        self.stripe_type = stripe_type
        self.stripe_code = stripe_code
        self.retryable = self.default_retryable if retryable is None else retryable
        self.outcome_unknown = outcome_unknown  # True: Stripe may have executed it; retry with the SAME key


class StripeConfigError(StripeError):
    """Missing or non-test key, or an unusable configuration. Maps to 503 CAPABILITY_UNAVAILABLE."""

    code = "CONFIG"


class StripeAmountNotAllowed(StripeError, ValueError):
    """The amount is not a server-allowlisted top-up. Maps to 422 INVALID_AMOUNT."""

    code = "AMOUNT_NOT_ALLOWED"


class StripeLocalValidationError(StripeError, ValueError):
    """Bad top-up id, return URL, session id, expiry or idempotency key. A server bug: 500 INTERNAL_ERROR."""

    code = "LOCAL_VALIDATION"


class StripeIdempotencyConflict(StripeError):
    """The same idempotency key with different parameters, refused locally or by Stripe. Never retry it."""

    code = "IDEMPOTENCY_CONFLICT"


class StripeAuthenticationError(StripeError):
    """HTTP 401: a bad or revoked key. Maps to 503 CAPABILITY_UNAVAILABLE."""

    code = "AUTHENTICATION"


class StripePermissionError(StripeError):
    """HTTP 403: the restricted key lacks a permission. Maps to 503 CAPABILITY_UNAVAILABLE."""

    code = "PERMISSION"


class StripeInvalidRequest(StripeError):
    """HTTP 400/402/404 invalid_request_error. Maps to 503 CAPABILITY_UNAVAILABLE and the operator log."""

    code = "INVALID_REQUEST"


class StripeConflict(StripeError):
    """HTTP 409: a concurrent request with the same idempotency key is still running. Retry the same key."""

    code = "CONFLICT"
    default_retryable = True


class StripeRateLimited(StripeError):
    """HTTP 429: not executed. Retry later with the same key. Maps to 429 RATE_LIMITED."""

    code = "RATE_LIMITED"
    default_retryable = True


class StripeApiError(StripeError):
    """HTTP 5xx. For POST the outcome is unknown: retry the same key. Maps to 500 INTERNAL_ERROR (retryable)."""

    code = "API_ERROR"
    default_retryable = True


class StripeNetworkError(StripeError):
    """Connect, TLS or timeout failure. For POST the outcome is unknown. Maps to 500 INTERNAL_ERROR (retryable)."""

    code = "NETWORK"
    default_retryable = True


class StripeResponseError(StripeError):
    """The response is malformed, or the created session does not match the request. 500 INTERNAL_ERROR."""

    code = "BAD_RESPONSE"


class StripeLivemodeRefused(StripeError):
    """Stripe returned a live-mode object. Refused (TEST mode only). 503 CAPABILITY_UNAVAILABLE."""

    code = "LIVEMODE_REFUSED"


# ------------------------------------------------------------------------------------------------
# Secrets (never echoed)
# ------------------------------------------------------------------------------------------------
def parse_env_file(path: str | os.PathLike) -> dict[str, str]:
    """Minimal dotenv reader: KEY=VALUE lines, optional ``export``, matching quotes, # comments."""
    values: dict[str, str] = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            if text.startswith("export "):
                text = text[7:].lstrip()
            key, sep, value = text.partition("=")
            if not sep:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            values[key.strip()] = value
    return values


def read_secret(name: str, *, env_file: str | os.PathLike | None = None,
                environ: Mapping[str, str] | None = None) -> str | None:
    """Look up a secret in the process environment first, then in an env file. Returns None if absent."""
    env = os.environ if environ is None else environ
    value = env.get(name)
    if value:
        return value.strip()
    if env_file is not None and os.path.isfile(env_file):
        value = parse_env_file(env_file).get(name)
        if value:
            return value.strip()
    return None


def require_test_key(value: object) -> str:
    """Refuse anything but a Stripe TEST-mode secret or restricted key. The value is never echoed."""
    if (
        not isinstance(value, str)
        or not value.startswith(TEST_KEY_PREFIXES)
        or len(value) < 24
        or any(ch.isspace() or ord(ch) < 0x21 or ord(ch) > 0x7E for ch in value)
    ):
        raise StripeConfigError(
            "Refusing to run: STRIPE_SECRET_KEY must be a Stripe TEST-mode key (sk_test_ or rk_test_). "
            "Live and publishable keys are never accepted."
        )
    return value


def load_test_secret_key(*, env_file: str | os.PathLike | None = None,
                         environ: Mapping[str, str] | None = None) -> str:
    value = read_secret(SECRET_KEY_ENV_NAME, env_file=env_file, environ=environ)
    if not value:
        raise StripeConfigError(f"{SECRET_KEY_ENV_NAME} is not configured; payment_mode stays UNAVAILABLE.")
    return require_test_key(value)


# ------------------------------------------------------------------------------------------------
# Pure request building
# ------------------------------------------------------------------------------------------------
def validate_topup_amount(amount_minor: object, limits: Limits | None = None) -> int:
    """CONTRACTS §9.2: presets 500/1,000/5,000, or custom 500–10,000 in steps of 100. Strict int only."""
    lim = limits or Limits()
    if type(amount_minor) is not int:  # rejects bool, float, str and int subclasses
        raise StripeAmountNotAllowed("amount_minor must be an integer number of minor units")
    if amount_minor in lim.topup_presets_minor:
        return amount_minor
    if lim.topup_min_minor <= amount_minor <= lim.topup_max_minor and amount_minor % lim.topup_step_minor == 0:
        return amount_minor
    raise StripeAmountNotAllowed(
        f"top-up must be a preset {list(lim.topup_presets_minor)} or {lim.topup_min_minor}-"
        f"{lim.topup_max_minor} in steps of {lim.topup_step_minor}"
    )


def validate_topup_id(topup_id: object) -> str:
    if not isinstance(topup_id, str) or not _TOPUP_ID_RE.fullmatch(topup_id):
        raise StripeLocalValidationError("topup_id must look like top_<32 lowercase hex>")
    return topup_id


def validate_return_url(url: object, name: str) -> str:
    """https URLs, or http on loopback only (local dev). No credentials, whitespace or control characters."""
    if not isinstance(url, str) or not url or len(url) > 2048:
        raise StripeLocalValidationError(f"{name} must be a URL of at most 2048 characters")
    if any(ch.isspace() or ord(ch) < 0x21 or ord(ch) == 0x7F for ch in url):
        raise StripeLocalValidationError(f"{name} contains whitespace or control characters")
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        raise StripeLocalValidationError(f"{name} is not a valid URL") from None
    if parts.username is not None or parts.password is not None:
        raise StripeLocalValidationError(f"{name} must not contain credentials")
    if parts.scheme == "https" and host:
        return url
    if parts.scheme == "http" and host in _LOOPBACK_HOSTS:
        return url
    raise StripeLocalValidationError(f"{name} must be https (or http on loopback)")


def validate_idempotency_key(key: object) -> str:
    if not isinstance(key, str) or not _IDEMPOTENCY_KEY_RE.fullmatch(key):
        raise StripeLocalValidationError("idempotency_key must be 8-255 characters of [A-Za-z0-9:_.-]")
    return key


def validate_session_id(session_id: object) -> str:
    if not isinstance(session_id, str) or not _TEST_SESSION_ID_RE.fullmatch(session_id):
        raise StripeLocalValidationError("session_id must be a TEST-mode Checkout Session id (cs_test_...)")
    return session_id


def topup_idempotency_key(topup_id: str) -> str:
    """Recommended stable key: derived only from the internal top-up id (no PII)."""
    return f"fazetime:topup:{validate_topup_id(topup_id)}"


def build_checkout_params(
    amount_minor: int,
    topup_id: str,
    success_url: str,
    cancel_url: str,
    *,
    expires_at: int | None = None,
    now: float | None = None,
    limits: Limits | None = None,
) -> list[tuple[str, str]]:
    """Ordered form parameters for POST /v1/checkout/sessions. Deterministic for the same inputs."""
    amount = validate_topup_amount(amount_minor, limits)
    validate_topup_id(topup_id)
    params = [
        ("mode", "payment"),
        ("allowed_payment_method_types[0]", CHECKOUT_PAYMENT_METHOD),
        ("managed_payments[enabled]", "false"),  # required with allowed_payment_method_types on MP accounts
        ("line_items[0][quantity]", "1"),
        ("line_items[0][price_data][currency]", CHECKOUT_CURRENCY),
        ("line_items[0][price_data][unit_amount]", str(amount)),
        ("line_items[0][price_data][product_data][name]", CHECKOUT_PRODUCT_NAME),
        ("success_url", validate_return_url(success_url, "success_url")),
        ("cancel_url", validate_return_url(cancel_url, "cancel_url")),
        ("client_reference_id", topup_id),
        ("metadata[topup_id]", topup_id),
    ]
    if expires_at is not None:
        current = time.time() if now is None else now
        if type(expires_at) is not int or not (
            current + CHECKOUT_MIN_EXPIRY_S - 60 <= expires_at <= current + CHECKOUT_MAX_EXPIRY_S
        ):
            raise StripeLocalValidationError("expires_at must be an int 30 min to 24 h after now (Unix seconds)")
        params.append(("expires_at", str(expires_at)))
    return params


def encode_form(params: list[tuple[str, str]]) -> bytes:
    return urlencode(params).encode("ascii")


def checkout_request_fingerprint(params: list[tuple[str, str]], api_version: str = STRIPE_API_VERSION) -> str:
    """SHA-256 over method, path, API version and the exact form body. Store it with the top-up row."""
    digest = hashlib.sha256()
    digest.update(f"POST /v1/checkout/sessions\n{api_version}\n".encode("ascii"))
    digest.update(encode_form(params))
    return digest.hexdigest()


class IdempotencyRegistry:
    """In-process guard: one fingerprint per idempotency key (bounded, thread-safe).

    This is a fast local refusal only. Durable protection is the backend's topups row (UNIQUE key and
    stored fingerprint), which survives restarts and outlives Stripe's 24 h key retention.
    """

    def __init__(self, max_entries: int = 10_000) -> None:
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, str] = OrderedDict()
        self._max = max_entries

    def claim(self, key: str, fingerprint: str) -> None:
        with self._lock:
            known = self._entries.get(key)
            if known is not None and known != fingerprint:
                raise StripeIdempotencyConflict(
                    "Refused locally: this idempotency key was already used with different Checkout parameters"
                )
            self._entries[key] = fingerprint
            self._entries.move_to_end(key)
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)


# ------------------------------------------------------------------------------------------------
# Transport and client
# ------------------------------------------------------------------------------------------------
Transport = Callable[[str, str, dict, "bytes | None", float], "tuple[int, dict[str, str], bytes]"]


def https_transport(host: str = STRIPE_API_HOST, port: int = 443) -> Transport:
    """http.client over verified TLS. No proxies, no redirects (credentials never leave api.stripe.com)."""
    context = ssl.create_default_context()

    def send(method: str, path: str, headers: dict, body: bytes | None, timeout: float):
        conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=context)
        try:
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read(MAX_RESPONSE_BYTES + 1)
            if len(data) > MAX_RESPONSE_BYTES:
                raise StripeResponseError("Stripe response exceeded the size cap")
            return resp.status, {k.lower(): v for k, v in resp.getheaders()}, data
        finally:
            conn.close()

    return send


@dataclass(frozen=True)
class CheckoutSession:
    facts: CheckoutSessionFacts
    url: str | None = field(repr=False)  # hosted payment link: hand to the buyer's browser, never log it
    expires_at: int | None
    payment_method_types: tuple[str, ...]
    request_id: str | None
    stripe_version: str | None  # the Stripe-Version response header, if present
    idempotent_replayed: bool
    managed_payments_enabled: bool | None = None  # None if the response omits the field

    @property
    def session_id(self) -> str:
        return self.facts.session_id

    @property
    def status(self) -> str | None:
        return self.facts.status

    @property
    def payment_status(self) -> str | None:
        return self.facts.payment_status

    @property
    def livemode(self) -> bool:
        return self.facts.livemode

    @property
    def url_host(self) -> str | None:
        return urlsplit(self.url).hostname if self.url else None


def _path_for_log(path: str) -> str:
    return re.sub(r"cs_test_[A-Za-z0-9]+", lambda m: m.group(0)[:12] + "...", path)


def _error_from_response(status: int, headers: dict[str, str], raw: bytes, method: str) -> StripeError:
    request_id = headers.get("request-id")
    detail: dict = {}
    try:
        doc = json.loads(raw.decode("utf-8"))
        if isinstance(doc, dict) and isinstance(doc.get("error"), dict):
            detail = doc["error"]
    except (UnicodeDecodeError, ValueError):
        pass
    stripe_type = detail.get("type") if isinstance(detail.get("type"), str) else None
    stripe_code = detail.get("code") if isinstance(detail.get("code"), str) else None
    message = detail.get("message") if isinstance(detail.get("message"), str) else f"HTTP {status} from Stripe"
    message = f"Stripe HTTP {status}: {message[:400]}"
    should_retry = headers.get("stripe-should-retry")
    kwargs = dict(http_status=status, request_id=request_id, stripe_type=stripe_type, stripe_code=stripe_code)
    if stripe_type == "idempotency_error":
        return StripeIdempotencyConflict(message, **kwargs)
    if status == 401:
        return StripeAuthenticationError(message, **kwargs)
    if status == 403:
        return StripePermissionError(message, **kwargs)
    if status == 409:
        return StripeConflict(message, retryable=should_retry != "false", outcome_unknown=method == "POST", **kwargs)
    if status == 429:
        return StripeRateLimited(message, retryable=should_retry != "false", **kwargs)
    if status >= 500:
        return StripeApiError(message, retryable=should_retry != "false", outcome_unknown=method == "POST", **kwargs)
    if status in (400, 402, 404):
        return StripeInvalidRequest(message, **kwargs)
    return StripeError(message, **kwargs)


class StripeTestClient:
    """Thread-safe Stripe TEST-mode client: Checkout Session create, retrieve and expire."""

    def __init__(
        self,
        secret_key: str,
        *,
        api_version: str = STRIPE_API_VERSION,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_network_retries: int = 1,
        transport: Transport | None = None,
        idempotency_registry: IdempotencyRegistry | None = None,
        sleep: Callable[[float], None] = time.sleep,
        limits: Limits | None = None,
    ) -> None:
        self.__key = require_test_key(secret_key)
        self.api_version = api_version
        self.timeout_s = float(timeout_s)
        self.max_network_retries = max(0, int(max_network_retries))
        self._transport = transport or https_transport()
        self._registry = idempotency_registry or IdempotencyRegistry()
        self._sleep = sleep
        self._limits = limits or Limits()

    def __repr__(self) -> str:
        return f"StripeTestClient(mode=TEST, key={self.key_kind}_[REDACTED], api_version={self.api_version!r})"

    __str__ = __repr__

    @property
    def key_kind(self) -> str:
        return self.__key[:7]  # "sk_test" or "rk_test"; never more

    # -- public API ------------------------------------------------------------------------------
    def create_checkout_session(
        self,
        amount_minor: int,
        topup_id: str,
        success_url: str,
        cancel_url: str,
        idempotency_key: str,
        *,
        expires_at: int | None = None,
    ) -> CheckoutSession:
        """Create (or idempotently replay) one hosted Checkout Session for an allowlisted amount."""
        params = build_checkout_params(amount_minor, topup_id, success_url, cancel_url,
                                       expires_at=expires_at, limits=self._limits)
        key = validate_idempotency_key(idempotency_key)
        self._registry.claim(key, checkout_request_fingerprint(params, self.api_version))
        headers, doc = self._request("POST", "/v1/checkout/sessions", form=params, idempotency_key=key)
        session = self._session(doc, headers)
        facts = session.facts
        problems = []
        if facts.amount_total != amount_minor:
            problems.append("amount_total")
        if facts.currency != CHECKOUT_CURRENCY:
            problems.append("currency")
        if facts.topup_id != topup_id or facts.client_reference_id != topup_id:
            problems.append("topup reference")
        if facts.mode != "payment":
            problems.append("mode")
        if session.payment_method_types != (CHECKOUT_PAYMENT_METHOD,):
            problems.append("payment_method_types")
        if not session.url or not session.url.startswith("https://"):
            problems.append("url")
        if session.managed_payments_enabled is True:
            problems.append("managed_payments")
        if problems:
            raise StripeResponseError(
                f"created Checkout Session does not match the request ({', '.join(problems)}); do not show it",
                request_id=session.request_id,
            )
        return session

    def retrieve_session(self, session_id: str) -> CheckoutSession:
        sid = validate_session_id(session_id)
        headers, doc = self._request("GET", f"/v1/checkout/sessions/{sid}")
        return self._session(doc, headers)

    def expire_session(self, session_id: str, *, idempotency_key: str | None = None) -> CheckoutSession:
        """Expire an OPEN session (Stripe then emits checkout.session.expired). No payment is affected."""
        sid = validate_session_id(session_id)
        key = validate_idempotency_key(idempotency_key) if idempotency_key is not None else None
        headers, doc = self._request("POST", f"/v1/checkout/sessions/{sid}/expire", form=[], idempotency_key=key)
        return self._session(doc, headers)

    # -- internals -------------------------------------------------------------------------------
    def _session(self, doc: object, headers: dict[str, str]) -> CheckoutSession:
        request_id = headers.get("request-id")
        try:
            facts = session_facts_from_object(doc)
        except LivemodeEventRejected:
            raise StripeLivemodeRefused("Stripe returned a LIVE-mode object; refused (TEST mode only)",
                                        request_id=request_id) from None
        except EventParseError as exc:
            raise StripeResponseError(f"unexpected Checkout Session shape ({exc.code})", request_id=request_id) from None
        url = doc.get("url")
        expires_at = doc.get("expires_at")
        methods = doc.get("payment_method_types")
        managed = doc.get("managed_payments")
        managed_enabled = managed.get("enabled") if isinstance(managed, dict) else None
        return CheckoutSession(
            facts=facts,
            url=url if isinstance(url, str) else None,
            expires_at=expires_at if type(expires_at) is int else None,
            payment_method_types=tuple(m for m in methods if isinstance(m, str)) if isinstance(methods, list) else (),
            request_id=request_id,
            stripe_version=headers.get("stripe-version"),
            idempotent_replayed=headers.get("idempotent-replayed", "").lower() == "true",
            managed_payments_enabled=managed_enabled if isinstance(managed_enabled, bool) else None,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        form: list[tuple[str, str]] | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[dict[str, str], dict]:
        body = encode_form(form) if form is not None else None
        headers = {
            "Authorization": f"Bearer {self.__key}",
            "Stripe-Version": self.api_version,
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        if method == "POST":
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        attempt = 0
        while True:
            attempt += 1
            started = time.monotonic()
            try:
                status, resp_headers, raw = self._transport(method, path, headers, body, self.timeout_s)
            except StripeError:
                raise
            except (OSError, http.client.HTTPException) as exc:  # includes timeouts and TLS errors
                err = StripeNetworkError(
                    f"network error talking to Stripe ({type(exc).__name__}); "
                    + ("outcome unknown, retry with the same idempotency key" if method == "POST" else "not completed"),
                    outcome_unknown=method == "POST",
                )
                log.warning("stripe %s %s network error %s attempt=%d", method, _path_for_log(path),
                            type(exc).__name__, attempt)
                if attempt <= self.max_network_retries:
                    self._sleep(min(2.0, 0.5 * 2 ** (attempt - 1)))
                    continue
                raise err from None
            elapsed_ms = (time.monotonic() - started) * 1000
            request_id = resp_headers.get("request-id")
            log.info("stripe %s %s -> %s request_id=%s attempt=%d %.0fms", method, _path_for_log(path), status,
                     request_id, attempt, elapsed_ms)
            if 200 <= status < 300:
                try:
                    doc = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    raise StripeResponseError("Stripe returned a non-JSON body", http_status=status,
                                              request_id=request_id) from None
                if not isinstance(doc, dict):
                    raise StripeResponseError("Stripe returned a non-object body", http_status=status,
                                              request_id=request_id)
                return resp_headers, doc
            err = _error_from_response(status, resp_headers, raw, method)
            if err.retryable and attempt <= self.max_network_retries:
                self._sleep(min(2.0, 0.5 * 2 ** (attempt - 1)))
                continue
            raise err
