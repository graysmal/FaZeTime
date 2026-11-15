"""P2-C presence: server-stamped heartbeats, per-(user, stream) aggregation, 45 s TTL, no economic effect."""

from __future__ import annotations

from fazetime_api import presence
from fazetime_api.schemas import PresenceAck

from .conftest import op


def _beat(h, actor, device_id, tab_id=None, **extra):
    body = {"device_id": device_id, "tab_instance_id": tab_id or op(), "stream_id": h.stream()["stream_id"],
            "known_stream_session_id": h.stream()["run_id"], "observed_channel_login": "fazetime_demo",
            "page_visibility": "VISIBLE", "player_state": "PLAYING", "extension_version": "0.1.0", **extra}
    return h.client.post("/v1/presence", headers=actor.h, json=body)


def _summary(h):
    with h.svc.db.read() as conn:
        return presence.summary(conn, h.stream()["stream_id"], h.clock.now(), h.svc.settings)


def _ledger_count(h):
    with h.svc.db.read() as conn:
        return conn.execute("SELECT COUNT(*) FROM ledger_transactions").fetchone()[0]


def test_heartbeat_is_server_stamped_and_aggregated_per_user(world):
    h, operator, alice, bob = world
    ledger_before = _ledger_count(h)
    laptop, other = op(), op()
    r = _beat(h, alice, laptop)
    assert r.status_code == 200, r.text
    ack = PresenceAck.model_validate(r.json())
    assert ack.last_seen_utc == ack.server_time_utc == "2026-11-14T20:00:00.000Z"
    assert (ack.heartbeat_interval_ms, ack.presence_ttl_ms) == (15000, 45000)
    assert ack.current_stream_session_id == h.stream()["run_id"]
    h.clock.advance(seconds=5)
    assert _beat(h, alice, laptop).status_code == 200  # second tab on the same device: same row
    assert _beat(h, alice, other, page_visibility="HIDDEN", player_state="PAUSED").status_code == 200
    summary = _summary(h)
    assert summary["present_users"] == 1 and len(summary["users"]) == 1  # multiple tabs/devices, one user
    entry = summary["users"][0]
    assert entry["user_id"] == alice.user_id and entry["devices"] == 2 and entry["presence_state"] == "PRESENT"
    with h.svc.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 3  # no duplicate users
    assert _ledger_count(h) == ledger_before  # presence never touches the ledger
    health = h.client.get("/v1/operator/health", headers=operator.h).json()
    assert health["presence"]["present_users"] == 1


def test_stopping_heartbeats_expires_presence_after_ttl(world):
    h, _, alice, _ = world
    assert _beat(h, alice, op()).status_code == 200
    h.clock.advance(ms=44_999)
    assert _summary(h)["users"][0]["presence_state"] == "PRESENT"
    h.clock.advance(ms=1)  # 45 s without a heartbeat
    assert _summary(h)["users"][0]["presence_state"] == "ABSENT"
    assert _summary(h)["present_users"] == 0
    assert _beat(h, alice, op()).status_code == 200
    assert _summary(h)["present_users"] == 1


def test_presence_authz_and_validation(world):
    h, _, alice, bob = world
    device = op()
    assert _beat(h, alice, device, user_id=bob.user_id).json()["error"]["code"] == "VALIDATION_FAILED"
    r = h.client.post("/v1/presence", json={"device_id": device})
    assert r.status_code == 401
    r = _beat(h, alice, device, stream_id="str_" + "0" * 32)
    assert r.status_code == 404
    assert _beat(h, alice, "not-a-uuid").status_code == 422
