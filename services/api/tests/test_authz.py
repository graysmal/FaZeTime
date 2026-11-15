"""Identity and authorization (§9.8, PROJECT_PLAN P2 gate: wrong user/session cannot read or act)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from fazetime_api.schemas import ErrorEnvelope, Me

from .conftest import op

OPERATOR_POSTS = [
    "/v1/operator/invites",
    "/v1/operator/streams",
    "/v1/operator/runs/reset",
    "/v1/operator/credits",
    "/v1/operator/markets",
    "/v1/operator/markets/mkt_00000000000000000000000000000000/open",
    "/v1/operator/markets/mkt_00000000000000000000000000000000/settle",
    "/v1/operator/markets/mkt_00000000000000000000000000000000/void",
    "/v1/operator/sessions/revoke",
]
# §9.21: CALL_WORKER fzk_ tokens only; any session (viewer or operator) is FORBIDDEN
CALL_POSTS = [
    "/v1/call/intents",
    "/v1/call/intents/wit_00000000000000000000000000000000/confirm",
    "/v1/call/intents/wit_00000000000000000000000000000000/cancel",
]


def _code(r, status, code):
    assert r.status_code == status, r.text
    ErrorEnvelope.model_validate(r.json())
    assert r.json()["error"]["code"] == code
    return r.json()["error"]


def test_unauthenticated_gets_401_envelope(world):
    h, *_ = world
    for method, path in [("GET", "/v1/me"), ("GET", "/v1/operations/" + op()), ("POST", "/v1/wagers"),
                         ("POST", "/v1/ws-ticket"), ("GET", f"/v1/streams/{h.stream()['stream_id']}/snapshot"),
                         ("GET", "/v1/operator/health"), ("POST", "/v1/topups"), ("GET", "/v1/call/overview"),
                         *(("POST", p) for p in CALL_POSTS)]:
        r = h.client.request(method, path)
        _code(r, 401, "UNAUTHENTICATED")
        assert r.headers["www-authenticate"] == "Bearer"
    _code(h.client.get("/v1/me", headers={"Authorization": "Bearer fzs_not_a_real_token"}), 401, "UNAUTHENTICATED")
    _code(h.client.get("/v1/me", headers={"Authorization": "Basic abc"}), 401, "UNAUTHENTICATED")


def test_token_in_query_string_is_ignored(world):
    h, _, alice, _ = world
    _code(h.client.get(f"/v1/me?token={alice.token}"), 401, "UNAUTHENTICATED")


@pytest.mark.parametrize("path", OPERATOR_POSTS + CALL_POSTS)
def test_viewer_cannot_call_operator_routes(world, path):
    h, _, alice, _ = world
    _code(h.client.post(path, headers=alice.h, json={"operation_id": op()}), 403, "FORBIDDEN")


@pytest.mark.parametrize("path", CALL_POSTS)
def test_operator_session_cannot_call_bookie_routes(world, path):
    h, operator, *_ = world
    _code(h.client.post(path, headers=operator.h, json={}), 403, "FORBIDDEN")
    _code(h.client.get("/v1/call/overview", headers=operator.h), 403, "FORBIDDEN")


def test_viewer_cannot_read_operator_inspection(world):
    h, _, alice, _ = world
    _code(h.client.get("/v1/operator/health", headers=alice.h), 403, "FORBIDDEN")
    _code(h.client.get("/v1/operator/ledger", headers=alice.h), 403, "FORBIDDEN")


def test_wrong_session_cannot_read_another_users_operation_or_wallet(world):
    h, operator, alice, bob = world
    market = h.open_market(operator)
    key = op()
    assert h.wager(alice, market, "YES", 700, operation_id=key).status_code == 201
    _code(h.client.get(f"/v1/operations/{key}", headers=bob.h), 404, "NOT_FOUND")
    me = h.client.get("/v1/me", headers=bob.h).json()
    Me.model_validate(me)
    assert me["user"]["user_id"] == bob.user_id and me["wallet"]["available_minor"] == 2000
    snap = h.snapshot(bob)
    assert snap["my_position"]["result"] == "NONE" and snap["my_position"]["wagers"] == []
    assert snap["wallet"]["available_minor"] == 2000
    # there is no viewer route that accepts a user_id; a body that names one is rejected outright
    r = h.wager(bob, market, "YES", 500, user_id=alice.user_id)
    _code(r, 422, "VALIDATION_FAILED")


def test_invite_binds_role_and_bot_flag_and_enroll_cannot_override(world):
    h, operator, *_ = world
    code = h.invite(operator)
    r = h.client.post("/v1/enroll", json={"invite_code": code, "display_name": "Eve", "device_id": op(),
                                          "role": "OPERATOR"})
    _code(r, 422, "VALIDATION_FAILED")
    r = h.client.post("/v1/enroll", json={"invite_code": code, "display_name": "Eve", "device_id": op(),
                                          "is_bot": True})
    _code(r, 422, "VALIDATION_FAILED")
    eve = h.enroll(code, "Eve")  # the code was not consumed by the rejected attempts
    assert h.client.get("/v1/me", headers=eve.h).json()["user"]["role"] == "VIEWER"
    bot = h.enroll(h.invite(operator, is_bot=True), "Bot")
    with h.svc.db.read() as conn:
        assert conn.execute("SELECT is_bot FROM users WHERE user_id = ?", (bot.user_id,)).fetchone()[0] == 1
    op2 = h.enroll(h.invite(operator, role="OPERATOR"), "Op2")
    assert h.client.get("/v1/operator/health", headers=op2.h).status_code == 200


def test_invite_single_use_expiry_and_indistinguishable_failures(world):
    h, operator, *_ = world
    code = h.invite(operator)
    h.enroll(code.lower(), "First")  # case- and hyphen-insensitive
    body = {"display_name": "X", "device_id": op()}
    used = _code(h.client.post("/v1/enroll", json={**body, "invite_code": code}), 401, "UNAUTHENTICATED")
    bad = _code(h.client.post("/v1/enroll", json={**body, "invite_code": "ZZZZ-ZZZZ-ZZZZ"}), 401, "UNAUTHENTICATED")
    junk = _code(h.client.post("/v1/enroll", json={**body, "invite_code": "!!"}), 401, "UNAUTHENTICATED")
    expiring = h.invite(operator)
    h.clock.advance(seconds=24 * 3600)
    expired = _code(h.client.post("/v1/enroll", json={**body, "invite_code": expiring}), 401, "UNAUTHENTICATED")
    assert used["message"] == bad["message"] == junk["message"] == expired["message"]


def test_session_expiry_and_revocation(world):
    h, operator, alice, bob = world
    r = h.client.post("/v1/operator/sessions/revoke", headers=operator.h,
                      json={"operation_id": op(), "user_id": bob.user_id})
    assert r.status_code == 200 and r.json()["revoked_sessions"] == 1
    _code(h.client.get("/v1/me", headers=bob.h), 401, "UNAUTHENTICATED")
    assert h.client.get("/v1/me", headers=alice.h).status_code == 200
    h.clock.advance(seconds=72 * 3600)
    _code(h.client.get("/v1/me", headers=alice.h), 401, "UNAUTHENTICATED")


def test_recovery_invite_binds_existing_user_without_new_seed(world):
    h, operator, alice, _ = world
    r = h.client.post("/v1/operator/invites", headers=operator.h,
                      json={"operation_id": op(), "role": "VIEWER", "bind_user_id": alice.user_id})
    assert r.status_code == 201
    again = h.enroll(r.json()["invite_code"], "Alice2")
    assert again.user_id == alice.user_id
    assert h.available(again) == 2000  # same wallet, no second SEED_GRANT
    assert h.reconcile()["ok"]


def test_invite_code_is_never_stored_or_replayed(world):
    h, operator, *_ = world
    key = op()
    first = h.client.post("/v1/operator/invites", headers=operator.h, json={"operation_id": key, "role": "VIEWER"})
    code = first.json()["invite_code"]
    replay = h.client.post("/v1/operator/invites", headers=operator.h, json={"operation_id": key, "role": "VIEWER"})
    assert replay.status_code == 200 and replay.json()["replayed"] is True and replay.json()["invite_code"] is None
    with h.svc.db.read() as conn:
        dump = "\n".join(str(tuple(r)) for t in ("operations", "audit_log", "invite_codes", "events")
                         for r in conn.execute(f"SELECT * FROM {t}"))
    assert code not in dump and code.replace("-", "") not in dump


def test_capabilities_unavailable_until_p6(world):
    h, _, alice, _ = world
    for method, path in [("POST", "/v1/topups"), ("GET", "/v1/topups/x"), ("POST", "/v1/redemptions"),
                         ("GET", "/v1/raffle")]:
        _code(h.client.request(method, path, headers=alice.h), 503, "CAPABILITY_UNAVAILABLE")


def test_no_phone_fields_in_schema(world):
    h, *_ = world
    with h.svc.db.read() as conn:
        for table in [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]:
            columns = [c[1] for c in conn.execute(f"PRAGMA table_info({table})")]
            assert not any("phone" in c or "card" in c for c in columns), (table, columns)


def test_unknown_route_and_method_use_envelope(world):
    h, *_ = world
    _code(h.client.get("/v1/nope"), 404, "NOT_FOUND")
    r = h.client.delete("/v1/me")
    assert r.status_code == 405 and r.json()["error"]["code"] == "NOT_FOUND"


PINNED = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"


def _preflight(client, origin):
    return client.options("/v1/me", headers={"Origin": origin, "Access-Control-Request-Method": "GET",
                                             "Access-Control-Request-Headers": "authorization"})


def test_cors_exact_pinned_extension_only(db_path, clock):
    from starlette.testclient import TestClient

    from fazetime_api.main import create_app

    from .conftest import make_settings

    settings = make_settings(db_path, allowed_origins=("https://www.twitch.tv", PINNED))
    with TestClient(create_app(settings, clock)) as client:
        ok = _preflight(client, PINNED)
        assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == PINNED
        for origin in ("chrome-extension://zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz", "https://evil.example",
                       "https://www.twitch.tv"):  # twitch.tv is CORS-allowed only via FAZETIME_CORS_ORIGINS (L7)
            _code(_preflight(client, origin), 403, "FORBIDDEN")
    with TestClient(create_app(settings.with_overrides(cors_origins=("https://www.twitch.tv",)), clock)) as client:
        assert _preflight(client, "https://www.twitch.tv").status_code == 200
        _code(_preflight(client, PINNED), 403, "FORBIDDEN")


def test_wildcard_origins_are_refused_in_config(monkeypatch):
    from fazetime_api.config import load_settings

    monkeypatch.setenv("FAZETIME_ALLOWED_ORIGINS", "https://www.twitch.tv,chrome-extension://*")
    with pytest.raises(ValueError):
        load_settings()


def test_operator_cannot_wager_and_has_no_wallet_d30(world):
    h, operator, alice, _ = world
    market = h.open_market(operator)
    _code(h.wager(operator, market, "YES", 500), 403, "FORBIDDEN")
    assert h.client.get("/v1/me", headers=operator.h).json()["wallet"] is None
    assert h.snapshot(operator)["wallet"]["available_minor"] == 0
    _code(h.credit(operator, operator.user_id, 500), 404, "NOT_FOUND")
    with h.svc.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM ledger_accounts a JOIN users u ON u.user_id = a.user_id"
                            " WHERE u.role = 'OPERATOR'").fetchone()[0] == 0
    assert h.wager(alice, market, "YES", 500).status_code == 201


def test_unmapped_4xx_is_validation_failed_422(db_path, clock):
    from starlette.exceptions import HTTPException
    from starlette.testclient import TestClient

    from fazetime_api.main import create_app

    from .conftest import make_settings

    app = create_app(make_settings(db_path), clock)

    def teapot():
        raise HTTPException(status_code=413)

    app.add_api_route("/v1/test-413", teapot, methods=["GET"])
    with TestClient(app) as client:
        _code(client.get("/v1/test-413"), 422, "VALIDATION_FAILED")


def test_body_cap_applies_before_buffering(world):
    h, _, alice, _ = world
    big = b'{"pad":"' + b"x" * 20_000 + b'"}'
    r = h.client.post("/v1/wagers", headers={**alice.h, "Content-Type": "application/json"}, content=big)
    assert "too large" in _code(r, 422, "VALIDATION_FAILED")["message"]

    def chunked():
        for _ in range(40):
            yield b"x" * 1024

    r = h.client.post("/v1/wagers", headers={**alice.h, "Content-Type": "application/json"}, content=chunked())
    assert "too large" in _code(r, 422, "VALIDATION_FAILED")["message"]
