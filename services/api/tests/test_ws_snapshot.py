"""WebSocket protocol and snapshot/event consistency (§9.9, §9.13 H)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from starlette.websockets import WebSocketDisconnect

from fazetime_api import timeutil
from fazetime_api.schemas import DomainEvent, PublicMarket, StreamSnapshot, WsTicketResponse

from .conftest import TWITCH, op, ws_recv


def _ticket(h, actor) -> dict:
    r = h.client.post("/v1/ws-ticket", headers=actor.h, json={"stream_id": h.stream()["stream_id"]})
    assert r.status_code == 200, r.text
    return WsTicketResponse.model_validate(r.json()).model_dump()


def _connect(h, origin: str | None = TWITCH):
    return h.client.websocket_connect("/v1/ws", headers={"origin": origin} if origin else {})


def _expect_close(ws, code: int, timeout: float = 3.0) -> None:
    with pytest.raises(WebSocketDisconnect) as exc:
        ws_recv(ws, timeout)
    assert exc.value.code == code


def _ready(h, actor) -> tuple:
    ticket = _ticket(h, actor)["ticket"]
    ws_cm = _connect(h)
    ws = ws_cm.__enter__()
    ws.send_json({"type": "auth", "ticket": ticket})
    ready = ws_recv(ws)
    assert ready["type"] == "ready" and isinstance(ready["event_hwm"], int)
    return ws_cm, ws, ready


def _max_event_id(h) -> int:
    with h.svc.db.read() as conn:
        return conn.execute("SELECT COALESCE(MAX(event_id), 0) FROM events").fetchone()[0]


def test_ticket_shape_and_url_has_no_secret(world):
    h, _, alice, _ = world
    t = _ticket(h, alice)
    assert t["ws_path"] == "/v1/ws" and t["ticket"].startswith("fzw_")
    assert timeutil.parse(t["expires_at_utc"]) - h.clock.now() == timedelta(seconds=30)


def test_events_arrive_after_commit_with_full_state_and_monotonic_versions(world):
    h, operator, alice, bob = world
    market = h.open_market(operator)
    ws_cm, ws, ready = _ready(h, alice)
    try:
        snap = h.snapshot(alice)
        assert snap["event_hwm"] == _max_event_id(h) and snap["event_hwm"] >= ready["event_hwm"]
        h.wager(bob, market, "NO", 500)  # bob's wallet/wager events are USER-scoped to bob
        h.wager(alice, market, "YES", 700)
        frames = [ws_recv(ws) for _ in range(4)]  # 2 x pool.updated, alice wager.updated, alice wallet.changed
        with pytest.raises(TimeoutError):
            ws_recv(ws, timeout=0.4)  # nothing else: bob's private events never reach alice
        events = [DomainEvent.model_validate(f["event"]) for f in frames if f["type"] == "event"]
        assert len(events) == 4
        assert [e.event_type for e in events].count("pool.updated") == 2
        assert all(e.audience == "PUBLIC" or e.payload.get("stream_session_id") for e in events)
        ids = [e.event_id for e in events]
        assert ids == sorted(ids) and min(ids) > ready["event_hwm"]
        pools = [e for e in events if e.event_type == "pool.updated"]
        assert [e.aggregate_version for e in pools] == sorted({e.aggregate_version for e in pools})
        last = PublicMarket.model_validate(pools[-1].payload)
        assert last.pool.total_minor == 1200 and last.aggregate_version == pools[-1].aggregate_version
        wallet = next(e for e in events if e.event_type == "wallet.changed")
        assert wallet.aggregate_id == alice.user_id and wallet.payload["available_minor"] == 1300
        wager = next(e for e in events if e.event_type == "wager.updated")
        assert wager.payload["amount_minor"] == 700 and wager.payload["status"] == "ACCEPTED"
        after = h.snapshot(alice)
        StreamSnapshot.model_validate(after)
        assert after["event_hwm"] == _max_event_id(h) >= max(ids)
        assert after["market"]["aggregate_version"] == last.aggregate_version
        # lock + evaluate + settle arrive in order, each carrying the full market
        h.clock.set(timeutil.parse(market["close_at_utc"]))
        h.sweep()
        h.settle(operator, market["market_id"], "YES")
        seen = [ws_recv(ws)["event"] for _ in range(5)]  # locked, evaluating, settled, wager, wallet
        market_events = [e for e in seen if e["aggregate_type"] == "MARKET"]
        assert [e["event_type"] for e in market_events] == ["market.locked", "market.evaluating", "market.settled"]
        versions = [e["aggregate_version"] for e in market_events]
        assert versions == sorted(versions) and versions[0] > last.aggregate_version
        assert market_events[-1]["payload"]["winning_side"] == "YES"
    finally:
        ws_cm.__exit__(None, None, None)


def test_all_persisted_aggregate_versions_strictly_increase(world):
    h, operator, alice, bob = world
    market = h.open_market(operator)
    for i in range(3):
        h.wager(alice, market, "YES", 100 * (i + 1))
        h.wager(bob, market, "NO", 200)
    h.clock.set(timeutil.parse(market["close_at_utc"]))
    h.sweep()
    h.settle(operator, market["market_id"], "NO")
    with h.svc.db.read() as conn:
        rows = conn.execute("SELECT run_id, aggregate_type, aggregate_id, aggregate_version FROM events"
                            " ORDER BY event_id").fetchall()
    last: dict = {}
    for r in rows:
        key = (r["run_id"], r["aggregate_type"], r["aggregate_id"])
        assert r["aggregate_version"] > last.get(key, 0), key
        last[key] = r["aggregate_version"]


def test_ticket_is_single_use(world):
    h, _, alice, _ = world
    ticket = _ticket(h, alice)["ticket"]
    with _connect(h) as ws:
        ws.send_json({"type": "auth", "ticket": ticket})
        assert ws_recv(ws)["type"] == "ready"
    with _connect(h) as ws:
        ws.send_json({"type": "auth", "ticket": ticket})
        _expect_close(ws, 4401)


def test_ticket_expires_after_30_seconds(world):
    h, _, alice, _ = world
    almost = _ticket(h, alice)["ticket"]
    expired = _ticket(h, alice)["ticket"]
    h.clock.advance(ms=29_999)
    with _connect(h) as ws:
        ws.send_json({"type": "auth", "ticket": almost})
        assert ws_recv(ws)["type"] == "ready"
    h.clock.advance(ms=1)  # exactly 30 s after issue
    with _connect(h) as ws:
        ws.send_json({"type": "auth", "ticket": expired})
        _expect_close(ws, 4401)


@pytest.mark.parametrize("frame", [{"type": "hello"}, {"type": "auth"}, {"type": "auth", "ticket": "fzw_nope"},
                                   {"type": "auth", "ticket": 12}, "not json", ["auth"]])
def test_bad_first_frame_closes_4401(world, frame):
    h, *_ = world
    with _connect(h) as ws:
        if isinstance(frame, str):
            ws.send_text(frame)
        else:
            ws.send_json(frame)
        _expect_close(ws, 4401)


def test_missing_first_frame_closes_4401(world):
    h, *_ = world
    with _connect(h) as ws:
        _expect_close(ws, 4401)  # ws_auth_timeout_s = 0.5 in tests (5 s in production)


@pytest.mark.parametrize("origin", ["https://evil.example", "http://www.twitch.tv", "https://www.twitch.tv.evil.example",
                                    "chrome-extension://abc/def", None])
def test_disallowed_origin_closes_4403(world, origin):
    h, _, alice, _ = world
    ticket = _ticket(h, alice)["ticket"]
    with _connect(h, origin) as ws:
        _expect_close(ws, 4403)
    with _connect(h) as ws:  # the ticket was not consumed by the rejected socket
        ws.send_json({"type": "auth", "ticket": ticket})
        assert ws_recv(ws)["type"] == "ready"


def test_extension_origin_allowed_and_ping_pong(world):
    h, _, alice, _ = world
    ticket = _ticket(h, alice)["ticket"]
    with _connect(h, "chrome-extension://abcdefghijklmnopabcdefghijklmnop") as ws:
        ws.send_json({"type": "auth", "ticket": ticket})
        assert ws_recv(ws)["type"] == "ready"
        ws.send_json({"type": "ping"})
        assert ws_recv(ws) == {"type": "pong"}


def test_revoked_session_ticket_is_rejected(world):
    h, operator, alice, _ = world
    ticket = _ticket(h, alice)["ticket"]
    r = h.client.post("/v1/operator/sessions/revoke", headers=operator.h,
                      json={"operation_id": op(), "user_id": alice.user_id})
    assert r.status_code == 200
    with _connect(h) as ws:
        ws.send_json({"type": "auth", "ticket": ticket})
        _expect_close(ws, 4401)


def test_snapshot_never_shows_draft_and_hwm_is_read_consistently(world):
    h, operator, alice, _ = world
    h.draft(operator)
    snap = h.snapshot(alice)
    assert snap["market"] is None and snap["my_position"] is None
    assert snap["event_hwm"] == _max_event_id(h)
    assert snap["source_health"]["state"] == "STOPPED" and snap["source_health"]["source_kind"] is None
    assert snap["modes"] == {"ai_mode": "OFF", "payment_mode": "UNAVAILABLE", "media_source_kind": None}
    assert h.client.get(f"/v1/streams/str_{'0' * 32}/snapshot", headers=alice.h).status_code == 404
