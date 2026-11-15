"""P6-B webhook signature verification and parsing (offline, simulated deliveries)."""

from __future__ import annotations

import json

import pytest

from fazetime_api.integrations.stripe_webhook import (
    CHECKOUT_COMPLETED,
    CHECKOUT_EXPIRED,
    EventParseError,
    LivemodeEventRejected,
    SignatureVerificationError,
    WebhookConfigError,
    compute_signature,
    construct_event,
    parse_event,
    verify_signature,
)

from .stripe_fixtures import (
    NOW,
    OTHER_SECRET,
    PI_ID,
    SECRET,
    SESSION_ID,
    TOPUP_ID,
    event_body,
    session_obj,
    signed_header,
    verified_event,
)

BODY = event_body(CHECKOUT_COMPLETED, session_obj())


def _sig(body: bytes = BODY, secret: str = SECRET, ts: int = NOW) -> str:
    return compute_signature(secret, ts, body)


# ---- signatures ----------------------------------------------------------------------------------
def test_valid_signature_returns_signed_timestamp():
    assert verify_signature(BODY, signed_header(BODY), SECRET, now=NOW) == NOW


def test_signature_is_hmac_sha256_over_timestamp_dot_raw_body():
    import hashlib
    import hmac

    expected = hmac.new(SECRET.encode(), f"{NOW}.".encode() + BODY, hashlib.sha256).hexdigest()
    assert _sig() == expected


def test_tampered_body_is_rejected():
    tampered = BODY.replace(b'"amount_total":500', b'"amount_total":5000')
    assert tampered != BODY
    with pytest.raises(SignatureVerificationError) as exc:
        verify_signature(tampered, signed_header(BODY), SECRET, now=NOW)
    assert exc.value.code == "SIGNATURE_MISMATCH"


def test_reserialized_body_is_rejected():
    """Parsing and re-dumping the JSON changes the bytes; only the raw body verifies."""
    reserialized = json.dumps(json.loads(BODY), indent=2).encode()
    with pytest.raises(SignatureVerificationError):
        verify_signature(reserialized, signed_header(BODY), SECRET, now=NOW)


def test_wrong_secret_is_rejected():
    with pytest.raises(SignatureVerificationError) as exc:
        verify_signature(BODY, signed_header(BODY, secret=OTHER_SECRET), SECRET, now=NOW)
    assert exc.value.code == "SIGNATURE_MISMATCH"


def test_expired_timestamp_is_rejected_and_boundary_is_accepted():
    header = signed_header(BODY, ts=NOW)
    assert verify_signature(BODY, header, SECRET, now=NOW + 300) == NOW
    with pytest.raises(SignatureVerificationError) as exc:
        verify_signature(BODY, header, SECRET, now=NOW + 301)
    assert exc.value.code == "TIMESTAMP_OUT_OF_TOLERANCE"


def test_far_future_timestamp_is_rejected():
    with pytest.raises(SignatureVerificationError) as exc:
        verify_signature(BODY, signed_header(BODY, ts=NOW + 900), SECRET, now=NOW)
    assert exc.value.code == "TIMESTAMP_OUT_OF_TOLERANCE"


def test_custom_tolerance_is_honoured():
    header = signed_header(BODY, ts=NOW)
    with pytest.raises(SignatureVerificationError):
        verify_signature(BODY, header, SECRET, tolerance_s=10, now=NOW + 11)
    assert verify_signature(BODY, header, SECRET, tolerance_s=10, now=NOW + 10) == NOW


@pytest.mark.parametrize("order", ["good_last", "good_first"])
def test_multiple_v1_signatures_any_match_is_accepted(order):
    good, bad = _sig(), _sig(secret=OTHER_SECRET)
    v1s = [f"v1={bad}", f"v1={good}"] if order == "good_last" else [f"v1={good}", f"v1={bad}"]
    header = ",".join([f"t={NOW}", *v1s])
    assert verify_signature(BODY, header, SECRET, now=NOW) == NOW


def test_unknown_v0_and_debug_entries_are_ignored_in_any_order():
    header = ",".join([
        "payload=a25aefc6",
        f"v1={_sig(secret=OTHER_SECRET)}",
        "secret=whsec_****************************PzVt",
        f"t={NOW}",
        f"v0={_sig()}",
        "destination=we_FIXTURE",
        "v9=future-scheme",
        "garbage-without-equals",
        f"v1={_sig()}",
    ])
    assert verify_signature(BODY, header, SECRET, now=NOW) == NOW


def test_v0_only_is_a_downgrade_and_rejected():
    with pytest.raises(SignatureVerificationError) as exc:
        verify_signature(BODY, f"t={NOW},v0={_sig()}", SECRET, now=NOW)
    assert exc.value.code == "NO_V1_SIGNATURE"


def test_mismatch_is_reported_before_the_timestamp_check():
    """Without a valid signature the caller learns nothing about the tolerance window."""
    with pytest.raises(SignatureVerificationError) as exc:
        verify_signature(BODY, f"t={NOW},v1={'0' * 64}", SECRET, now=NOW + 10_000)
    assert exc.value.code == "SIGNATURE_MISMATCH"


@pytest.mark.parametrize(
    "header, code",
    [
        ("", "MALFORMED_HEADER"),
        ("   ", "MALFORMED_HEADER"),
        (None, "MALFORMED_HEADER"),
        ("garbage", "MALFORMED_HEADER"),
        (f"v1={'a' * 64}", "MALFORMED_HEADER"),
        (f"t=abc,v1={'a' * 64}", "MALFORMED_HEADER"),
        (f"t=-5,v1={'a' * 64}", "MALFORMED_HEADER"),
        (f"t=1.5,v1={'a' * 64}", "MALFORMED_HEADER"),
        (f"t={NOW},t={NOW},v1={'a' * 64}", "MALFORMED_HEADER"),
        (f"t={NOW}", "NO_V1_SIGNATURE"),
        (f"t={NOW},v1=", "NO_V1_SIGNATURE"),
        ("t=1," + "v1=" + "a" * 5000, "MALFORMED_HEADER"),
    ],
)
def test_malformed_headers_are_rejected(header, code):
    with pytest.raises(SignatureVerificationError) as exc:
        verify_signature(BODY, header, SECRET, now=NOW)
    assert exc.value.code == code


def test_non_ascii_signature_value_does_not_crash():
    with pytest.raises(SignatureVerificationError):
        verify_signature(BODY, f"t={NOW},v1=ééé", SECRET, now=NOW)


def test_body_must_be_raw_bytes():
    with pytest.raises(TypeError):
        verify_signature(BODY.decode(), signed_header(BODY), SECRET, now=NOW)
    assert verify_signature(bytearray(BODY), signed_header(BODY), SECRET, now=NOW) == NOW


@pytest.mark.parametrize("secret", ["", "sk" "_test_FIXTUREfixtureFIXTURE", "whsec" "_", "whsec" "_ has space", None])
def test_bad_secret_is_a_config_error(secret):
    with pytest.raises(WebhookConfigError):
        verify_signature(BODY, signed_header(BODY), secret, now=NOW)


@pytest.mark.parametrize("tolerance", [0, -1, True, 1.5])
def test_non_positive_or_non_int_tolerance_is_refused(tolerance):
    with pytest.raises(ValueError):
        verify_signature(BODY, signed_header(BODY), SECRET, tolerance_s=tolerance, now=NOW)


def test_construct_event_verifies_before_parsing():
    junk = b"not json at all"
    with pytest.raises(SignatureVerificationError):
        construct_event(junk, f"t={NOW},v1={'0' * 64}", SECRET, now=NOW)
    with pytest.raises(EventParseError):  # correctly signed junk only fails at parse time
        construct_event(junk, signed_header(junk), SECRET, now=NOW)


# ---- livemode ------------------------------------------------------------------------------------
def test_livemode_event_is_rejected():
    body = event_body(CHECKOUT_COMPLETED, session_obj(), livemode=True)
    with pytest.raises(LivemodeEventRejected) as exc:
        construct_event(body, signed_header(body), SECRET, now=NOW)
    assert exc.value.code == "LIVEMODE_EVENT"


def test_livemode_object_inside_test_event_is_rejected():
    with pytest.raises(LivemodeEventRejected):
        verified_event(CHECKOUT_COMPLETED, session_obj(livemode=True))


def test_livemode_is_rejected_even_for_unhandled_types():
    body = event_body("payment_intent.succeeded", {"id": PI_ID, "object": "payment_intent", "livemode": True})
    with pytest.raises(LivemodeEventRejected):
        construct_event(body, signed_header(body), SECRET, now=NOW)


def test_live_session_id_is_rejected():
    with pytest.raises(LivemodeEventRejected):
        verified_event(CHECKOUT_COMPLETED, session_obj(id="cs_live_FIXTURE0001"))


# ---- parsing -------------------------------------------------------------------------------------
def test_handled_event_exposes_only_minimal_fields():
    event = verified_event(CHECKOUT_COMPLETED, event_id="evt_FIXTUREparse0001")
    assert event.handled is True
    assert (event.event_id, event.type, event.livemode, event.created) == ("evt_FIXTUREparse0001", CHECKOUT_COMPLETED,
                                                                           False, NOW)
    assert event.api_version == "2026-10-28.endive"
    assert len(event.payload_sha256) == 64
    s = event.session
    assert (s.session_id, s.status, s.payment_status, s.amount_total, s.currency) == (SESSION_ID, "complete", "paid",
                                                                                      500, "usd")
    assert (s.topup_id, s.client_reference_id, s.payment_intent_id, s.mode) == (TOPUP_ID, TOPUP_ID, PI_ID, "payment")
    assert s.is_paid
    assert not hasattr(s, "customer_details") and not hasattr(s, "customer_email")


def test_expanded_payment_intent_is_reduced_to_its_id():
    event = verified_event(CHECKOUT_COMPLETED, session_obj(payment_intent={"id": PI_ID, "object": "payment_intent"}))
    assert event.session.payment_intent_id == PI_ID


def test_expired_session_without_payment_intent_parses():
    event = verified_event(CHECKOUT_EXPIRED, session_obj(status="expired", payment_status="unpaid", payment_intent=None))
    assert event.handled and event.session.payment_intent_id is None and not event.session.is_paid


def test_uppercase_currency_is_normalised():
    assert verified_event(CHECKOUT_COMPLETED, session_obj(currency="USD")).session.currency == "usd"


@pytest.mark.parametrize("event_type", ["payment_intent.succeeded", "charge.refunded", "checkout.session.created",
                                        "customer.created"])
def test_unknown_types_parse_as_unhandled_without_session(event_type):
    event = verified_event(event_type, {"id": "obj_FIXTURE", "object": "whatever", "livemode": False})
    assert event.handled is False and event.session is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(object="v2.core.event"),
        lambda d: d.update(id="not-an-event-id"),
        lambda d: d.update(type="Bad Type"),
        lambda d: d.update(livemode="false"),
        lambda d: d.update(created="1800000000"),
        lambda d: d["data"].update(object={"id": SESSION_ID, "object": "payment_intent", "livemode": False}),
        lambda d: d["data"]["object"].update(amount_total=500.0),
        lambda d: d["data"]["object"].update(amount_total=True),
        lambda d: d["data"]["object"].update(amount_total=-1),
        lambda d: d["data"]["object"].update(currency="us"),
        lambda d: d["data"]["object"].update(metadata=["topup_id"]),
        lambda d: d["data"]["object"].update(metadata={"topup_id": 7}),
        lambda d: d["data"]["object"].update(payment_intent="ch_FIXTURE"),
        lambda d: d["data"]["object"].update(id="cs_FIXTURE"),
        lambda d: d["data"]["object"].update(status=["complete"]),
        lambda d: d["data"]["object"].pop("livemode"),
    ],
)
def test_malformed_handled_events_raise_parse_errors(mutate):
    doc = json.loads(BODY)
    mutate(doc)
    body = json.dumps(doc).encode()
    with pytest.raises(EventParseError):
        construct_event(body, signed_header(body), SECRET, now=NOW)


@pytest.mark.parametrize("body", [b"", b"[]", b"{", b"\xff\xfe", b"null", json.dumps({"object": "event"}).encode()])
def test_non_event_bodies_raise_parse_errors(body):
    with pytest.raises(EventParseError):
        parse_event(body)


def test_oversized_body_is_refused_before_json_decoding():
    big = b'{"object":"event","pad":"' + b"x" * (256 * 1024) + b'"}'
    with pytest.raises(EventParseError) as exc:
        parse_event(big)
    assert exc.value.code == "TOO_LARGE"
