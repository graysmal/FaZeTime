"""D35 open access (FAZETIME_OPEN_ACCESS): name-only viewer enrollment and the shared no-sign-in operator session.

Flag on: a blank invite_code enrolls a NEW non-bot VIEWER (own session, own SEED_GRANT wallet), and
POST /v1/open/operator-session returns a session for ONE shared OPERATOR account (no wallet, cannot wager: D30).
Flag off (default): a blank code is the same 401 as a bad code, and the open route is a plain 404.
Every test runs against a real SQLite file (conftest)."""

from __future__ import annotations

import logging
import re
import threading

import pytest
from starlette.testclient import TestClient

from fazetime_api import auth, timeutil
from fazetime_api.config import load_settings
from fazetime_api.errors import ApiError
from fazetime_api.ids import id_pattern
from fazetime_api.main import create_app
from fazetime_api.schemas import EnrollResponse, ErrorEnvelope

from .conftest import Actor, Harness, make_settings, op

OPEN_PATH = "/v1/open/operator-session"


def _code(r, status, code):
    assert r.status_code == status, r.text
    ErrorEnvelope.model_validate(r.json())
    assert r.json()["error"]["code"] == code
    return r.json()["error"]


@pytest.fixture
def oh(db_path, clock):
    """Harness with open access ON."""
    app = create_app(make_settings(db_path, open_access=True), clock)
    with TestClient(app) as client:
        yield Harness(client, clock)


def _name_only(h: Harness, name: str = "Walk-in", **extra):
    return h.client.post("/v1/enroll", json={"display_name": name, "device_id": op(), **extra})


def _actor(r) -> Actor:
    assert r.status_code == 201, r.text
    data = r.json()
    return Actor(data["session_token"], data["me"]["user"]["user_id"], data["session_id"])


def _open_operator(h: Harness) -> tuple[Actor, dict]:
    r = h.client.post(OPEN_PATH, json={"device_id": op()})
    assert r.status_code == 201, r.text
    assert r.headers["cache-control"] == "no-store"
    EnrollResponse.model_validate(r.json())
    return _actor(r), r.json()


def _seed_txns(h: Harness, user_id: str) -> int:
    with h.svc.db.read() as conn:
        return conn.execute("SELECT COUNT(*) FROM ledger_transactions WHERE reason = 'SEED_GRANT'"
                            " AND source_key LIKE ?", (f"seed:%:{user_id}",)).fetchone()[0]


# ---- flag on ---------------------------------------------------------------------------------------------------
def test_name_only_enroll_creates_seeded_viewer(oh):
    operator, _ = _open_operator(oh)
    oh.create_stream(operator)
    r = _name_only(oh, "Walk-in", claimed_twitch_login="walk_in_1")
    assert r.status_code == 201 and r.headers["cache-control"] == "no-store"
    body = r.json()
    EnrollResponse.model_validate(body)  # exactly the invite-enrollment response shape
    assert set(body) == {"schema_version", "session_token", "session_id", "expires_at_utc", "me"}
    user = body["me"]["user"]
    assert user["role"] == "VIEWER" and user["display_name"] == "Walk-in" and user["claimed_twitch_login"] == "walk_in_1"
    assert body["me"]["wallet"]["available_minor"] == 2000 and body["me"]["wallet"]["in_play_minor"] == 0
    viewer = _actor(r)
    assert oh.available(viewer) == 2000 and _seed_txns(oh, viewer.user_id) == 1
    with oh.svc.db.read() as conn:
        row = conn.execute("SELECT role, is_bot FROM users WHERE user_id = ?", (viewer.user_id,)).fetchone()
        assert (row["role"], row["is_bot"]) == ("VIEWER", 0)
        dev = conn.execute("SELECT device_id FROM sessions WHERE session_id = ?", (viewer.session_id,)).fetchone()
        assert dev[0] is not None
    assert oh.snapshot(viewer)["modes"]["open_access"] is True
    assert oh.reconcile()["ok"]


def test_blank_and_null_codes_are_name_only_and_each_join_is_a_new_account(oh):
    operator, _ = _open_operator(oh)
    oh.create_stream(operator)
    a = _actor(_name_only(oh, "Same", invite_code=""))
    b = _actor(_name_only(oh, "Same", invite_code="   "))
    c = _actor(_name_only(oh, "Same", invite_code=None))
    assert len({a.user_id, b.user_id, c.user_id}) == 3  # same name, three accounts and three wallets
    for actor in (a, b, c):
        assert oh.available(actor) == 2000 and _seed_txns(oh, actor.user_id) == 1
    assert oh.reconcile()["ok"]


def test_name_only_viewer_wagers_and_settles_like_any_viewer(oh):
    operator, _ = _open_operator(oh)
    oh.create_stream(operator)
    alice = _actor(_name_only(oh, "Alice"))
    bob = _actor(_name_only(oh, "Bob"))
    market = oh.open_market(operator)
    assert oh.wager(alice, market, "YES", 500).status_code == 201
    assert oh.wager(bob, market, "NO", 500).status_code == 201
    oh.clock.set(timeutil.parse(market["close_at_utc"]))
    oh.sweep()
    assert oh.settle(operator, market["market_id"], "YES").status_code == 200
    assert oh.available(alice) == 2500 and oh.available(bob) == 1500  # parimutuel, no fee
    assert oh.reconcile()["ok"]


def test_name_only_enroll_before_a_stream_is_seeded_when_the_stream_is_created(oh):
    early = _actor(_name_only(oh, "Early"))
    assert oh.client.get("/v1/me", headers=early.h).json()["wallet"] is None
    operator, _ = _open_operator(oh)
    oh.create_stream(operator)
    assert oh.available(early) == 2000 and _seed_txns(oh, early.user_id) == 1


def test_open_operator_session_is_one_shared_operator_without_wallet(oh, caplog):
    caplog.set_level(logging.DEBUG)
    first, body = _open_operator(oh)
    assert body["me"]["user"] == {"user_id": auth.OPEN_OPERATOR_USER_ID, "display_name": "Operator",
                                  "claimed_twitch_login": None, "role": "OPERATOR"}
    assert body["me"]["wallet"] is None
    oh.create_stream(first)
    second, body2 = _open_operator(oh)
    assert second.user_id == first.user_id == auth.OPEN_OPERATOR_USER_ID
    assert second.session_id != first.session_id and second.token != first.token
    assert body2["me"]["wallet"] is None  # D30: no seed grant even with an active run
    for actor in (first, second):  # both sessions stay valid and carry the OPERATOR role
        health = oh.client.get("/v1/operator/health", headers=actor.h)
        assert health.status_code == 200
        assert health.json()["open_access"] is True and health.json()["modes"]["open_access"] is True
    health = oh.client.get("/v1/operator/health", headers=first.h).json()
    assert any(label.startswith("OPEN ACCESS") for label in health["service"]["mode_labels"])
    assert first.user_id not in {w["user_id"] for w in health["wallets"]}
    with oh.svc.db.read() as conn:
        users = conn.execute("SELECT role, is_bot, display_name FROM users WHERE role = 'OPERATOR'").fetchall()
        assert [tuple(u) for u in users] == [("OPERATOR", 0, "Operator")]
        assert conn.execute("SELECT COUNT(*) FROM ledger_accounts WHERE user_id = ?",
                            (first.user_id,)).fetchone()[0] == 0
        rows = conn.execute("SELECT actor_user_id, actor_kind, target_type, target_id, detail_json FROM audit_log"
                            " WHERE action = 'OPEN_OPERATOR_SESSION' ORDER BY audit_id").fetchall()
        assert [(r["actor_kind"], r["target_type"], r["target_id"]) for r in rows] == [
            ("SYSTEM", "SESSION", first.session_id), ("SYSTEM", "SESSION", second.session_id)]
        assert '"account_created":true' in rows[0]["detail_json"].replace(" ", "")
        assert '"account_created":false' in rows[1]["detail_json"].replace(" ", "")
        invites = conn.execute("SELECT role, is_bot, bind_user_id, used_by_user_id, used_at_utc FROM invite_codes"
                               " WHERE invite_id IN (SELECT invite_id FROM sessions WHERE user_id = ?)",
                               (first.user_id,)).fetchall()
        assert len(invites) == 2 and all(i["used_at_utc"] is not None for i in invites)  # consumed at birth
        assert all((i["role"], i["is_bot"], i["used_by_user_id"]) == ("OPERATOR", 0, first.user_id) for i in invites)
        dump = "\n".join(str(tuple(r)) for t in ("sessions", "audit_log", "invite_codes", "events", "operations")
                         for r in conn.execute(f"SELECT * FROM {t}"))
    for token in (first.token, second.token):
        assert token not in dump and token not in caplog.text  # never stored or logged
    assert first.session_id in caplog.text  # the issue itself is logged (without the token)


def test_open_operator_can_operate_but_cannot_wager(oh):
    operator, _ = _open_operator(oh)
    oh.create_stream(operator)
    viewer = _actor(_name_only(oh, "Viewer"))
    market = oh.open_market(operator)
    _code(oh.wager(operator, market, "YES", 500), 403, "FORBIDDEN")  # D30
    assert oh.wager(viewer, market, "YES", 500).status_code == 201
    r = oh.client.post(f"/v1/operator/markets/{market['market_id']}/void", headers=operator.h,
                       json={"operation_id": op()})
    assert r.status_code == 200 and r.json()["market"]["state"] == "VOID"
    assert oh.available(viewer) == 2000 and oh.reconcile()["ok"]


def test_open_operator_session_is_revocable_and_survives_restart(db_path, clock):
    settings = make_settings(db_path, open_access=True)
    with TestClient(create_app(settings, clock)) as client:
        first = _actor(client.post(OPEN_PATH, json={"device_id": op()}))
        keep = _actor(client.post(OPEN_PATH, json={"device_id": op()}))
    with TestClient(create_app(settings, clock)) as client:  # process restart: same DB file
        again = _actor(client.post(OPEN_PATH, json={"device_id": op()}))
        assert again.user_id == first.user_id == auth.OPEN_OPERATOR_USER_ID
        assert client.get("/v1/operator/health", headers=first.h).status_code == 200
        r = client.post("/v1/operator/sessions/revoke", headers=keep.h,
                        json={"operation_id": op(), "user_id": auth.OPEN_OPERATOR_USER_ID})
        assert r.status_code == 200 and r.json()["revoked_sessions"] == 3  # the shared account: all its sessions
        _code(client.get("/v1/operator/health", headers=first.h), 401, "UNAUTHENTICATED")
        assert _actor(client.post(OPEN_PATH, json={"device_id": op()})).user_id == auth.OPEN_OPERATOR_USER_ID


def test_concurrent_first_operator_sessions_create_exactly_one_account(oh):
    n = 8
    barrier = threading.Barrier(n)
    results: list[str] = []
    lock = threading.Lock()

    def worker():
        barrier.wait()
        with oh.svc.db.write() as conn:  # a fresh connection per thread: SQLite is the single-writer boundary
            body = auth.open_operator_session(conn, device_id=op(), client_host="race", now=oh.clock.now(),
                                              settings=oh.svc.settings)
        with lock:
            results.append(body["me"]["user"]["user_id"])

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert results == [auth.OPEN_OPERATOR_USER_ID] * n
    with oh.svc.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == n
        created = conn.execute("SELECT detail_json FROM audit_log WHERE action = 'OPEN_OPERATOR_SESSION'").fetchall()
        assert sum('"account_created": true' in r[0] or '"account_created":true' in r[0] for r in created) == 1


def test_invite_enroll_unchanged_with_open_access_on(oh):
    operator, _ = _open_operator(oh)
    oh.create_stream(operator)
    code = oh.invite(operator)
    viewer = oh.enroll(code, "Invited")
    assert oh.available(viewer) == 2000 and _seed_txns(oh, viewer.user_id) == 1
    body = {"display_name": "X", "device_id": op()}
    used = _code(oh.client.post("/v1/enroll", json={**body, "invite_code": code}), 401, "UNAUTHENTICATED")
    bad = _code(oh.client.post("/v1/enroll", json={**body, "invite_code": "ZZZZ-ZZZZ-ZZZZ"}), 401,
                "UNAUTHENTICATED")
    junk = _code(oh.client.post("/v1/enroll", json={**body, "invite_code": "!!"}), 401, "UNAUTHENTICATED")
    assert used["message"] == bad["message"] == junk["message"]  # a supplied code never falls back to name-only
    op_code = oh.invite(operator, role="OPERATOR")
    op2 = oh.enroll(op_code, "Op2")
    assert op2.user_id != auth.OPEN_OPERATOR_USER_ID  # invite operators stay separate accounts
    assert oh.client.get("/v1/operator/health", headers=op2.h).status_code == 200
    with oh.svc.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users WHERE display_name = 'X'").fetchone()[0] == 0


def test_name_only_body_cannot_choose_role_or_bot(oh):
    for extra in ({"role": "OPERATOR"}, {"is_bot": True}, {"user_id": auth.OPEN_OPERATOR_USER_ID}):
        _code(_name_only(oh, "Sneaky", **extra), 422, "VALIDATION_FAILED")
    viewer = _actor(_name_only(oh, "Operator"))  # the name alone grants nothing
    assert viewer.user_id != auth.OPEN_OPERATOR_USER_ID
    _code(oh.client.get("/v1/operator/health", headers=viewer.h), 403, "FORBIDDEN")
    _code(oh.client.post(OPEN_PATH, json={}), 422, "VALIDATION_FAILED")
    _code(oh.client.post(OPEN_PATH, json={"device_id": "not-a-uuid"}), 422, "VALIDATION_FAILED")
    _code(oh.client.post(OPEN_PATH, json={"device_id": op(), "role": "VIEWER"}), 422, "VALIDATION_FAILED")
    _code(_name_only(oh, "Long", invite_code="A" * 65), 422, "VALIDATION_FAILED")
    _code(oh.client.post("/v1/enroll", json={"device_id": op()}), 422, "VALIDATION_FAILED")  # name still required


def test_rate_limits_apply_with_open_access(db_path, clock):
    settings = make_settings(db_path, open_access=True, rl_enroll=(2, 600.0), rl_open_operator_session=(2, 600.0))
    with TestClient(create_app(settings, clock)) as client:
        h = Harness(client, clock)
        assert _name_only(h).status_code == 201 and _name_only(h).status_code == 201
        _code(_name_only(h), 429, "RATE_LIMITED")
        assert client.post(OPEN_PATH, json={"device_id": op()}).status_code == 201
        assert client.post(OPEN_PATH, json={"device_id": op()}).status_code == 201
        _code(client.post(OPEN_PATH, json={"device_id": op()}), 429, "RATE_LIMITED")


def test_stream_updated_event_modes_carry_open_access(oh):
    operator, _ = _open_operator(oh)
    oh.create_stream(operator)
    with oh.svc.db.read() as conn:
        payloads = [r[0] for r in conn.execute("SELECT payload_json FROM events WHERE event_type = 'stream.updated'")]
    assert payloads and all('"open_access": true' in p or '"open_access":true' in p for p in payloads)


# ---- flag off (default) ----------------------------------------------------------------------------------------
def test_open_access_off_name_only_is_401_and_operator_route_is_404(world):
    h, operator, alice, _ = world
    assert h.svc.settings.open_access is False
    bad = _code(h.client.post("/v1/enroll", json={"invite_code": "ZZZZ-ZZZZ-ZZZZ", "display_name": "X",
                                                  "device_id": op()}), 401, "UNAUTHENTICATED")
    for body in ({}, {"invite_code": ""}, {"invite_code": "  "}, {"invite_code": None}):
        r = _name_only(h, "NoCode", **body)
        assert _code(r, 401, "UNAUTHENTICATED")["message"] == bad["message"]  # identical to a bad code
    for method in ("POST", "GET"):
        r = h.client.request(method, OPEN_PATH, json={"device_id": op()} if method == "POST" else None)
        assert _code(r, 404, "NOT_FOUND")["message"] == "Not found."
    unknown = _code(h.client.post("/v1/open/nothing-here", json={}), 404, "NOT_FOUND")
    assert unknown["message"] == "Not found."  # the off route is indistinguishable from an unknown path
    assert OPEN_PATH not in h.client.get("/openapi.json").json()["paths"]
    with h.svc.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users WHERE display_name = 'NoCode'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM users WHERE user_id = ?",
                            (auth.OPEN_OPERATOR_USER_ID,)).fetchone()[0] == 0
    assert h.snapshot(alice)["modes"]["open_access"] is False
    health = h.client.get("/v1/operator/health", headers=operator.h).json()
    assert health["open_access"] is False and health["modes"]["open_access"] is False
    assert not any(label.startswith("OPEN ACCESS") for label in health["service"]["mode_labels"])


def test_open_operator_session_function_refuses_when_off(h):
    with pytest.raises(ApiError) as exc:
        with h.svc.db.write() as conn:
            auth.open_operator_session(conn, device_id=op(), client_host="x", now=h.clock.now(),
                                       settings=h.svc.settings)
    assert exc.value.code == "NOT_FOUND"


@pytest.mark.parametrize("raw,expected", [(None, False), ("", False), ("0", False), ("false", False),
                                          ("1", True), ("true", True), ("TRUE", True)])
def test_env_flag_parsing(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("FAZETIME_OPEN_ACCESS", raising=False)
    else:
        monkeypatch.setenv("FAZETIME_OPEN_ACCESS", raw)
    assert load_settings().open_access is expected


def test_open_operator_user_id_is_valid_and_cannot_collide_with_new_ids():
    assert re.fullmatch(id_pattern("usr"), auth.OPEN_OPERATOR_USER_ID)
    assert auth.OPEN_OPERATOR_USER_ID[4:][12] != "4"  # new_id() is uuid4 hex: char 12 is always "4"
