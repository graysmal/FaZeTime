"""Shared fixtures. Every test uses a REAL SQLite file in a tmp dir with the production pragmas."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

import anyio
import pytest
from starlette.testclient import TestClient

from fazetime_api import auth, timeutil
from fazetime_api.config import Settings
from fazetime_api.main import create_app
from fazetime_api.sweeper import sweep_once

START = "2026-11-14T20:00:00.000Z"
TWITCH = "https://www.twitch.tv"


def op() -> str:
    return str(uuid.uuid4())


def make_settings(db_path: str, **overrides) -> Settings:
    base = Settings(
        db_path=db_path,
        sweeper_enabled=False,  # tests drive the sweeper explicitly with the fake clock
        ws_auth_timeout_s=0.5,
        ws_ping_interval_s=30.0,
        ws_session_recheck_s=0.3,
        rl_enroll=(1000, 60.0),
        rl_wager=(1000, 10.0),
        rl_ws_ticket=(1000, 60.0),
        rl_presence=(1000, 60.0),
    )
    return base.with_overrides(**overrides)


@dataclass
class Actor:
    token: str
    user_id: str
    session_id: str

    @property
    def h(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}


class Harness:
    def __init__(self, client: TestClient, clock: timeutil.FakeClock):
        self.client = client
        self.clock = clock
        self.app = client.app
        self.svc = client.app.state.svc

    # ---- identity ----
    def bootstrap_operator(self, name: str = "Op") -> Actor:
        with self.svc.db.write() as conn:
            _, code = auth.create_invite(conn, role="OPERATOR", is_bot=False, bind_user_id=None,
                                         created_by_user_id=None, now=self.clock.now(), settings=self.svc.settings)
        return self.enroll(code, name)

    def enroll(self, code: str, name: str = "Viewer", **extra) -> Actor:
        body = {"invite_code": code, "display_name": name, "device_id": op(), **extra}
        r = self.client.post("/v1/enroll", json=body)
        assert r.status_code == 201, r.text
        data = r.json()
        return Actor(data["session_token"], data["me"]["user"]["user_id"], data["session_id"])

    def invite(self, operator: Actor, role: str = "VIEWER", is_bot: bool = False) -> str:
        r = self.client.post("/v1/operator/invites", headers=operator.h,
                             json={"operation_id": op(), "role": role, "is_bot": is_bot})
        assert r.status_code == 201, r.text
        return r.json()["invite_code"]

    def viewer(self, operator: Actor, name: str = "Viewer", is_bot: bool = False) -> Actor:
        return self.enroll(self.invite(operator, is_bot=is_bot), name)

    # ---- stream / markets ----
    def create_stream(self, operator: Actor, login: str = "fazetime_demo") -> dict:
        r = self.client.post("/v1/operator/streams", headers=operator.h,
                             json={"operation_id": op(), "twitch_channel_login": login})
        assert r.status_code in (200, 201), r.text
        return r.json()["stream"]

    def stream(self) -> dict:
        with self.svc.db.read() as conn:
            s = conn.execute("SELECT stream_id FROM streams").fetchone()
            r = conn.execute("SELECT run_id FROM runs WHERE state = 'ACTIVE'").fetchone()
        return {"stream_id": s["stream_id"], "run_id": r["run_id"]}

    def draft(self, operator: Actor, close_in_s: int = 60, resolve_in_s: int = 120, **kw) -> dict:
        body = {"operation_id": op(), "question": kw.pop("question", "Will FaZeGavin win round 1?"),
                "close_in_s": close_in_s, "resolve_in_s": resolve_in_s, **kw}
        r = self.client.post("/v1/operator/markets", headers=operator.h, json=body)
        assert r.status_code == 201, r.text
        return r.json()["market"]

    def open(self, operator: Actor, market_id: str) -> dict:
        r = self.client.post(f"/v1/operator/markets/{market_id}/open", headers=operator.h,
                             json={"operation_id": op()})
        assert r.status_code == 200, r.text
        return r.json()["market"]

    def open_market(self, operator: Actor, **kw) -> dict:
        return self.open(operator, self.draft(operator, **kw)["market_id"])

    def wager(self, actor: Actor, market: dict, side: str = "YES", amount: int = 500, operation_id: str | None = None,
              **override):
        body = {"operation_id": operation_id or op(), "stream_session_id": market["stream_session_id"],
                "market_id": market["market_id"], "rules_version": market["rules_version"], "side": side,
                "amount_minor": amount, **override}
        return self.client.post("/v1/wagers", headers=actor.h, json=body)

    def settle(self, operator: Actor, market_id: str, side: str, operation_id: str | None = None):
        return self.client.post(f"/v1/operator/markets/{market_id}/settle", headers=operator.h,
                                json={"operation_id": operation_id or op(), "winning_side": side})

    def credit(self, operator: Actor, user_id: str, amount: int, operation_id: str | None = None):
        return self.client.post("/v1/operator/credits", headers=operator.h,
                                json={"operation_id": operation_id or op(), "user_id": user_id,
                                      "amount_minor": amount})

    def sweep(self) -> dict:
        return sweep_once(self.svc.db, self.clock, self.svc.settings)

    def snapshot(self, actor: Actor) -> dict:
        r = self.client.get(f"/v1/streams/{self.stream()['stream_id']}/snapshot", headers=actor.h)
        assert r.status_code == 200, r.text
        return r.json()

    def available(self, actor: Actor) -> int:
        return self.client.get("/v1/me", headers=actor.h).json()["wallet"]["available_minor"]

    def reconcile(self) -> dict:
        from fazetime_api import ledger
        with self.svc.db.read() as conn:
            return ledger.reconcile(conn).as_dict()


def ws_recv(ws, timeout: float = 3.0) -> dict:
    """Receive one JSON frame with a timeout (Starlette's TestClient receive() blocks forever)."""

    async def _recv():
        with anyio.fail_after(timeout):
            return await ws._send_rx.receive()

    message = ws.portal.call(_recv)
    ws._raise_on_close(message)
    return json.loads(message["text"])


@pytest.fixture
def clock() -> timeutil.FakeClock:
    return timeutil.FakeClock(START)


@pytest.fixture
def db_path(tmp_path) -> str:
    return str(tmp_path / "fazetime-test.db")


@pytest.fixture
def h(db_path, clock):
    app = create_app(make_settings(db_path), clock)
    with TestClient(app) as client:
        yield Harness(client, clock)


@pytest.fixture
def world(h):
    """Operator + stream + two funded viewers (2,000 seed each)."""
    operator = h.bootstrap_operator()
    h.create_stream(operator)
    alice = h.viewer(operator, "Alice")
    bob = h.viewer(operator, "Bob")
    return h, operator, alice, bob
