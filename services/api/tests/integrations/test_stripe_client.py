"""P6-A Checkout adapter against a fake transport (offline; no network, no real key)."""

from __future__ import annotations

import json
from urllib.parse import parse_qsl

import pytest

from fazetime_api.integrations import stripe_client as sc
from fazetime_api.integrations.stripe_client import (
    STRIPE_API_VERSION,
    StripeTestClient,
    build_checkout_params,
    checkout_request_fingerprint,
    load_test_secret_key,
    validate_topup_amount,
)

from .stripe_fixtures import FAKE_KEY, NOW, OTHER_TOPUP_ID, SESSION_ID, TOPUP_ID, session_obj

SUCCESS = "https://www.twitch.tv/fixture_channel?fazetime_topup=" + TOPUP_ID
CANCEL = "https://www.twitch.tv/fixture_channel?fazetime_topup=" + TOPUP_ID + "&fazetime_result=cancel"
KEY = "fazetime:topup:" + TOPUP_ID
CHECKOUT_URL = "https://checkout.stripe.com/c/pay/" + SESSION_ID + "#fidFIXTURE"


def open_session(**overrides) -> dict:
    doc = session_obj(status="open", payment_status="unpaid", payment_intent=None, url=CHECKOUT_URL,
                      customer_details=None, expires_at=NOW + 86_400)
    doc.update(overrides)
    return doc


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, method, path, headers, body, timeout):
        self.calls.append({"method": method, "path": path, "headers": dict(headers), "body": body, "timeout": timeout})
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def ok(doc: dict, **headers) -> tuple:
    return 200, {"request-id": "req_FIXTURE0001", **headers}, json.dumps(doc).encode()


def fail(status: int, err_type: str, message: str = "fixture error", **headers) -> tuple:
    body = json.dumps({"error": {"type": err_type, "message": message, "code": "fixture_code"}}).encode()
    return status, {"request-id": "req_FIXTURE0002", **headers}, body


def client(*responses, retries: int = 0, sleeps: list | None = None) -> tuple[StripeTestClient, FakeTransport]:
    transport = FakeTransport(*responses)
    sleeper = (sleeps.append if sleeps is not None else (lambda s: None))
    return StripeTestClient(FAKE_KEY, transport=transport, max_network_retries=retries, sleep=sleeper), transport


def create(c: StripeTestClient, amount: int = 500, key: str = KEY, topup_id: str = TOPUP_ID):
    return c.create_checkout_session(amount, topup_id, SUCCESS, CANCEL, key)


# ---- key handling --------------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [
    "sk" "_live_FIXTUREfixtureFIXTUREfixture", "rk" "_live_FIXTUREfixtureFIXTUREfixture", "pk" "_test_FIXTUREfixtureFIXTURE00",
    "whsec" "_FIXTUREfixtureFIXTUREfixture00", "sk" "_test_short", "sk" "_test_FIXTURE with spaces inside", "", None,
])
def test_non_test_keys_are_refused_without_echoing_them(bad):
    with pytest.raises(sc.StripeConfigError) as exc:
        StripeTestClient(bad, transport=FakeTransport())
    if bad:
        assert bad not in str(exc.value)


@pytest.mark.parametrize("good", [FAKE_KEY, "rk" "_test_FIXTUREfixtureFIXTUREfixture"])
def test_test_keys_are_accepted_and_never_shown(good):
    c = StripeTestClient(good, transport=FakeTransport())
    assert good not in repr(c) and good not in str(c)
    assert c.key_kind in ("sk_test", "rk_test")


def test_key_loads_from_env_file_without_leaking(tmp_path):
    env = tmp_path / ".env.local"
    env.write_text(f'# comment\nOTHER=1\nexport STRIPE_SECRET_KEY="{FAKE_KEY}"\n')
    assert load_test_secret_key(env_file=env, environ={}) == FAKE_KEY
    live = "sk" "_live_FIXTUREfixtureFIXTUREfixture"
    env.write_text(f"STRIPE_SECRET_KEY={live}\n")
    with pytest.raises(sc.StripeConfigError) as exc:
        load_test_secret_key(env_file=env, environ={})
    assert live not in str(exc.value)
    assert load_test_secret_key(env_file=env, environ={"STRIPE_SECRET_KEY": FAKE_KEY}) == FAKE_KEY  # env wins
    with pytest.raises(sc.StripeConfigError):
        load_test_secret_key(env_file=tmp_path / "missing", environ={})


# ---- amount allowlist and request shape ----------------------------------------------------------
@pytest.mark.parametrize("amount", [500, 1_000, 5_000, 600, 2_300, 9_900, 10_000])
def test_allowlisted_amounts(amount):
    assert validate_topup_amount(amount) == amount


@pytest.mark.parametrize("amount", [0, -500, 100, 400, 450, 550, 10_001, 10_100, 20_000, 10**12, 500.0, "500", True,
                                    None])
def test_disallowed_amounts_are_refused_before_any_request(amount):
    c, transport = client()
    with pytest.raises(sc.StripeAmountNotAllowed):
        c.create_checkout_session(amount, TOPUP_ID, SUCCESS, CANCEL, KEY)
    assert transport.calls == []


def test_checkout_params_are_card_only_usd_single_line_with_topup_metadata_only():
    params = build_checkout_params(1_000, TOPUP_ID, SUCCESS, CANCEL)
    keys = [k for k, _ in params]
    assert len(keys) == len(set(keys))
    d = dict(params)
    assert d["mode"] == "payment"
    assert d["allowed_payment_method_types[0]"] == "card"
    assert d["managed_payments[enabled]"] == "false"  # measured: MP-default accounts reject the filter otherwise
    assert not any(k.startswith("payment_method_types") for k in keys)  # removed in 2026-09-30.endive
    assert [k for k in keys if k.startswith("line_items[")] == [
        "line_items[0][quantity]", "line_items[0][price_data][currency]",
        "line_items[0][price_data][unit_amount]", "line_items[0][price_data][product_data][name]",
    ]
    assert d["line_items[0][quantity]"] == "1"
    assert d["line_items[0][price_data][currency]"] == "usd"
    assert d["line_items[0][price_data][unit_amount]"] == "1000"
    assert d["line_items[0][price_data][product_data][name]"] == "FaZeTime demo credits (TEST)"
    assert [k for k in keys if k.startswith("metadata")] == ["metadata[topup_id]"]
    assert d["metadata[topup_id]"] == TOPUP_ID and d["client_reference_id"] == TOPUP_ID
    assert not any(k.startswith(("customer", "payment_intent_data", "setup", "subscription", "saved_payment"))
                   for k in keys)


def test_create_sends_pinned_version_idempotency_key_and_form_body():
    c, transport = client(ok(open_session()))
    session = create(c)
    (call,) = transport.calls
    assert call["method"] == "POST" and call["path"] == "/v1/checkout/sessions"
    h = call["headers"]
    assert h["Stripe-Version"] == STRIPE_API_VERSION == "2026-10-28.endive"
    assert h["Idempotency-Key"] == KEY
    assert h["Authorization"] == f"Bearer {FAKE_KEY}"  # header only, never in the path or body
    assert h["Content-Type"] == "application/x-www-form-urlencoded"
    assert call["timeout"] == sc.DEFAULT_TIMEOUT_S
    assert FAKE_KEY not in call["path"] and FAKE_KEY.encode() not in call["body"]
    assert parse_qsl(call["body"].decode()) == build_checkout_params(500, TOPUP_ID, SUCCESS, CANCEL)
    assert (session.session_id, session.url, session.expires_at) == (SESSION_ID, CHECKOUT_URL, NOW + 86_400)
    assert (session.status, session.payment_status, session.livemode) == ("open", "unpaid", False)
    assert session.url_host == "checkout.stripe.com" and session.request_id == "req_FIXTURE0001"
    assert CHECKOUT_URL not in repr(session)


def test_idempotency_key_reuse_with_changed_amount_is_refused_locally():
    c, transport = client(ok(open_session()))
    create(c, 500)
    with pytest.raises(sc.StripeIdempotencyConflict):
        create(c, 1_000)
    with pytest.raises(sc.StripeIdempotencyConflict):
        create(c, 500, topup_id=OTHER_TOPUP_ID)
    assert len(transport.calls) == 1  # refused before the network


def test_same_key_and_params_may_be_retried_and_stripe_replays():
    c, transport = client(ok(open_session()), ok(open_session(), **{"idempotent-replayed": "true"}))
    first, second = create(c), create(c)
    assert first.session_id == second.session_id and second.idempotent_replayed and not first.idempotent_replayed
    assert [call["headers"]["Idempotency-Key"] for call in transport.calls] == [KEY, KEY]


def test_registry_is_shared_across_clients_when_injected():
    registry = sc.IdempotencyRegistry()
    a = StripeTestClient(FAKE_KEY, transport=FakeTransport(ok(open_session())), idempotency_registry=registry)
    b = StripeTestClient(FAKE_KEY, transport=FakeTransport(), idempotency_registry=registry)
    create(a, 500)
    with pytest.raises(sc.StripeIdempotencyConflict):
        create(b, 5_000)


def test_remote_idempotency_error_is_typed_and_not_retried():
    c, transport = client(fail(400, "idempotency_error"), retries=3)
    with pytest.raises(sc.StripeIdempotencyConflict) as exc:
        create(c)
    assert exc.value.http_status == 400 and exc.value.retryable is False and len(transport.calls) == 1


def test_fingerprint_binds_every_parameter():
    base = checkout_request_fingerprint(build_checkout_params(500, TOPUP_ID, SUCCESS, CANCEL))
    assert base == checkout_request_fingerprint(build_checkout_params(500, TOPUP_ID, SUCCESS, CANCEL))
    assert base != checkout_request_fingerprint(build_checkout_params(1_000, TOPUP_ID, SUCCESS, CANCEL))
    assert base != checkout_request_fingerprint(build_checkout_params(500, TOPUP_ID, SUCCESS + "&x=1", CANCEL))
    assert base != checkout_request_fingerprint(build_checkout_params(500, TOPUP_ID, SUCCESS, CANCEL), "2026-08-26.dahlia")


def test_topup_idempotency_key_derives_from_topup_id_only():
    assert sc.topup_idempotency_key(TOPUP_ID) == KEY
    with pytest.raises(sc.StripeLocalValidationError):
        sc.topup_idempotency_key("fan@example.invalid")


# ---- retries and error mapping -------------------------------------------------------------------
def test_network_error_retries_with_the_same_key_then_reports_unknown_outcome():
    sleeps: list = []
    c, transport = client(TimeoutError("timed out"), ConnectionResetError("reset"), retries=1, sleeps=sleeps)
    with pytest.raises(sc.StripeNetworkError) as exc:
        create(c)
    assert exc.value.outcome_unknown is True and exc.value.retryable is True
    assert [call["headers"]["Idempotency-Key"] for call in transport.calls] == [KEY, KEY]
    assert sleeps == [0.5]


def test_network_error_then_success_returns_the_session():
    c, transport = client(OSError("connection refused"), ok(open_session()), retries=1)
    assert create(c).session_id == SESSION_ID and len(transport.calls) == 2


def test_server_error_honours_stripe_should_retry_false():
    c, transport = client(fail(500, "api_error", **{"stripe-should-retry": "false"}), retries=2)
    with pytest.raises(sc.StripeApiError) as exc:
        create(c)
    assert exc.value.retryable is False and exc.value.outcome_unknown is True and len(transport.calls) == 1


def test_server_error_is_retried_once_with_the_same_key():
    c, transport = client(fail(503, "api_error"), ok(open_session()), retries=1)
    assert create(c).session_id == SESSION_ID
    assert [call["headers"]["Idempotency-Key"] for call in transport.calls] == [KEY, KEY]


@pytest.mark.parametrize("status, err_type, exc_type", [
    (400, "invalid_request_error", sc.StripeInvalidRequest),
    (401, "invalid_request_error", sc.StripeAuthenticationError),
    (403, "invalid_request_error", sc.StripePermissionError),
    (404, "invalid_request_error", sc.StripeInvalidRequest),
    (409, "invalid_request_error", sc.StripeConflict),
    (429, "invalid_request_error", sc.StripeRateLimited),
    (500, "api_error", sc.StripeApiError),
])
def test_http_errors_map_to_typed_exceptions(status, err_type, exc_type):
    c, _ = client(fail(status, err_type))
    with pytest.raises(exc_type) as exc:
        create(c)
    assert exc.value.http_status == status and exc.value.request_id == "req_FIXTURE0002"


def test_error_messages_are_redacted():
    leaked = "Invalid API Key provided: sk" "_test_FIXTUREleakedLEAKED; see https://checkout.stripe.com/c/pay/cs_test_X"
    c, _ = client(fail(401, "invalid_request_error", leaked))
    with pytest.raises(sc.StripeAuthenticationError) as exc:
        create(c)
    text = str(exc.value)
    assert "sk" "_test_FIXTUREleakedLEAKED" not in text and "sk" "_test_[REDACTED]" in text
    assert "cs_test_X" not in text
    assert sc.redact("whsec" "_FIXTUREsecretSECRET") == "whsec" "_[REDACTED]"
    dashboard = "configure at https://dashboard.stripe.com/acct_FIXTURE123/test/settings/x."
    assert "acct_FIXTURE123" not in sc.redact(dashboard)
    assert sc.redact("account acct_FIXTURE456 here") == "account acct_[REDACTED] here"


def test_non_json_success_body_is_a_response_error():
    c, _ = client((200, {"request-id": "req_FIXTURE0003"}, b"<html>"))
    with pytest.raises(sc.StripeResponseError):
        create(c)


# ---- response checks -----------------------------------------------------------------------------
def test_livemode_response_is_refused():
    c, _ = client(ok(open_session(livemode=True)))
    with pytest.raises(sc.StripeLivemodeRefused):
        create(c)


@pytest.mark.parametrize("overrides", [
    {"amount_total": 1_000},
    {"currency": "eur"},
    {"metadata": {"topup_id": OTHER_TOPUP_ID}},
    {"client_reference_id": None},
    {"mode": "subscription"},
    {"payment_method_types": ["card", "link"]},
    {"payment_method_types": []},
    {"url": None},
    {"url": "http://checkout.stripe.com/c/pay/x"},
    {"managed_payments": {"enabled": True}},
])
def test_created_session_that_differs_from_the_request_is_refused(overrides):
    c, _ = client(ok(open_session(**overrides)))
    with pytest.raises(sc.StripeResponseError):
        create(c)


def test_retrieve_is_a_plain_get_without_body_or_idempotency_key():
    c, transport = client(ok(session_obj(status="complete", payment_status="paid")))
    session = c.retrieve_session(SESSION_ID)
    (call,) = transport.calls
    assert call["method"] == "GET" and call["path"] == f"/v1/checkout/sessions/{SESSION_ID}"
    assert call["body"] is None and "Idempotency-Key" not in call["headers"]
    assert call["headers"]["Stripe-Version"] == STRIPE_API_VERSION
    assert session.facts.is_paid and session.facts.topup_id == TOPUP_ID


@pytest.mark.parametrize("bad", ["cs_live_FIXTURE", "cs_test_../../v1/charges", "cs_test_", "", None,
                                 "cs_test_abc?expand[]=x", "pi_FIXTURE"])
def test_retrieve_refuses_bad_ids_without_network(bad):
    c, transport = client()
    with pytest.raises(sc.StripeLocalValidationError):
        c.retrieve_session(bad)
    assert transport.calls == []


def test_expire_posts_to_the_expire_path():
    c, transport = client(ok(open_session(status="expired")))
    assert c.expire_session(SESSION_ID).status == "expired"
    assert transport.calls[0]["method"] == "POST"
    assert transport.calls[0]["path"] == f"/v1/checkout/sessions/{SESSION_ID}/expire"


# ---- URL, id and expiry validation ---------------------------------------------------------------
@pytest.mark.parametrize("url", ["https://example.com/ok", "http://127.0.0.1:8000/return", "http://localhost/x",
                                 "https://www.twitch.tv/c?fazetime_topup={CHECKOUT_SESSION_ID}"])
def test_acceptable_return_urls(url):
    assert sc.validate_return_url(url, "success_url") == url


@pytest.mark.parametrize("url", ["http://example.com/x", "javascript:alert(1)", "https://user:pw@example.com/",
                                 "https://exa mple.com/", "https://example.com/\n", "ftp://example.com/",
                                 "https:///nohost", "https://example.com/" + "a" * 2100, "", None])
def test_unacceptable_return_urls(url):
    with pytest.raises(sc.StripeLocalValidationError):
        sc.validate_return_url(url, "success_url")


@pytest.mark.parametrize("topup_id", ["top_short", "TOP_" + "a" * 32, "top_" + "g" * 32, "", None, 7])
def test_bad_topup_ids_are_refused(topup_id):
    with pytest.raises(sc.StripeLocalValidationError):
        build_checkout_params(500, topup_id, SUCCESS, CANCEL)


@pytest.mark.parametrize("key", ["short", "has space here", "x" * 256, "line\nbreak-key", None])
def test_bad_idempotency_keys_are_refused(key):
    c, transport = client()
    with pytest.raises(sc.StripeLocalValidationError):
        c.create_checkout_session(500, TOPUP_ID, SUCCESS, CANCEL, key)
    assert transport.calls == []


def test_expires_at_is_validated_and_sent():
    params = dict(build_checkout_params(500, TOPUP_ID, SUCCESS, CANCEL, expires_at=NOW + 3_600, now=NOW))
    assert params["expires_at"] == str(NOW + 3_600)
    for bad in (NOW + 600, NOW + 90_000, float(NOW + 3_600)):
        with pytest.raises(sc.StripeLocalValidationError):
            build_checkout_params(500, TOPUP_ID, SUCCESS, CANCEL, expires_at=bad, now=NOW)
