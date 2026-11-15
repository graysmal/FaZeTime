"""In-process fake of the §9.16 worker routes (tests only). Mirrors the API's documented rules:
bearer fzk_ token, idempotent epochs, STALE_EPOCH for non-current epochs, (epoch, sequence) dedupe for
observations and evidence, FRAME items must reference evidence of the same epoch, error envelope."""
from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
EP = re.compile(r"^ep_[0-9a-f]{32}$")
STR = re.compile(r"^str_[0-9a-f]{32}$")
FLAGS = {"PARTIAL", "CLOSED_BY_GAP", "CLOSED_BY_PTS_DISCONTINUITY", "CLOSED_BY_STOP", "AFTER_GAP",
         "DRAINED_AFTER_STOP", "LATE_SPLIT", "PTS_UNKNOWN", "IN_DISCONTINUITY_HOLE", "LOW_CONFIDENCE",
         "DEDUPED_OVERLAP"}


class FakeApi:
    def __init__(self, token="fzk_" + "t" * 43, stream_id="str_" + "a" * 32):
        self.token, self.stream_id = token, stream_id
        self.lock = threading.Lock()
        self.epochs: dict[str, dict] = {}
        self.epoch_order: list[str] = []
        self.current: str | None = None
        self.observations: dict[tuple, dict] = {}
        self.evidence: dict[tuple, tuple] = {}
        self.evidence_epoch: dict[str, str] = {}
        self.heartbeats: list[dict] = []
        self.calls: list[tuple] = []
        self.fail_plan: list[tuple] = []  # (route_suffix, status, after_commit)
        self.auth_headers_seen: set[str] = set()
        # §9.17/§9.19 AI routes (generic profile tests): APPROVAL mode, the market view is set by the test
        self.proposals: list[dict] = []
        self.resolutions: list[dict] = []
        self.used_fingerprints: set[str] = set()
        self.market: dict | None = None
        self.evidence_ms: dict[str, int] = {}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def fail_next(self, route_suffix: str, status: int = 500, after_commit: bool = False, times: int = 1):
        with self.lock:
            self.fail_plan += [(route_suffix, status, after_commit)] * times

    # ---- route logic ----------------------------------------------------------------------------------
    @staticmethod
    def err(status, code, msg="", details=None):
        return status, {"error": {"code": code, "message": msg, "retryable": code in ("RATE_LIMITED", "INTERNAL_ERROR"),
                                  "retry_after_ms": None, "request_id": None, "operation_id": None,
                                  "details": details}, "server_time_utc": "2026-11-15T00:00:00.000Z"}

    def route(self, path, body, files=None):
        if path == "/v1/worker/epochs":
            return self._epochs(body)
        if path == "/v1/worker/heartbeat":
            return self._heartbeat(body)
        if path == "/v1/worker/observations":
            return self._observations(body)
        if path == "/v1/worker/evidence":
            return self._evidence(files)
        if path == "/v1/worker/proposals":
            return self._proposal(body)
        if path == "/v1/worker/resolutions":
            return self._resolution(body)
        return self.err(404, "NOT_FOUND")

    def get_route(self, path):
        if path.startswith("/v1/worker/market?stream_id="):
            return 200, {"schema_version": 1, "market": self.market}
        return self.err(404, "NOT_FOUND")

    GENERIC_KEYS = {"spec_version", "kind", "unit", "params", "episode_start_media_ms", "success_cue", "failure_cue"}
    GENERIC_OPTIONAL = {"expected_result_in_s"}  # §9.20 item 2: an int in [0, 900], or null
    PARAM_KEYS = {"EPISODE_OUTCOME": {"win_verb"}, "END_VALUE_AT_LEAST": {"label", "threshold"},
                  "SAY_PHRASE": {"phrase"}, "DURATION_OVER": {"duration_s"}}
    CANDIDATE_KEYS = {"candidate_id", "template_id", "episode_fingerprint", "question", "yes", "no", "subjects",
                      "evidence_ids", "announced_at_media_ms", "suggested_close_in_s", "suggested_resolve_in_s",
                      "cancellation_conditions", "rationale", "model", "prompt_version", "generic"}

    def ref_ms(self, epoch, ref):
        """(media_start_ms) of a known evidence reference in ``epoch`` (§9.17 item 5c), else None."""
        if ref.startswith("evd_"):
            return self.evidence_ms.get(ref) if self.evidence_epoch.get(ref) == epoch else None
        m = re.fullmatch(r"(ep_[0-9a-f]{32}):(\d+)", ref)
        it = self.observations.get((epoch, int(m.group(2)))) if m and m.group(1) == epoch else None
        return None if it is None or it["kind"] == "GAP" else it["media_start_ms"]

    def _proposal(self, b):
        c = b.get("candidate") or {}
        if set(c) != self.CANDIDATE_KEYS or c.get("template_id") != "GENERIC_BINARY_V1":
            return self.err(422, "VALIDATION_FAILED", "candidate fields")
        g = c["generic"]
        eta = g.get("expected_result_in_s") if isinstance(g, dict) else None
        if (not isinstance(g, dict) or not self.GENERIC_KEYS <= set(g) <= self.GENERIC_KEYS | self.GENERIC_OPTIONAL
                or g["spec_version"] != "gen-1" or set(g["params"]) != self.PARAM_KEYS.get(g["kind"], {None})
                or len(c["subjects"]) > 1
                or not (eta is None or (type(eta) is int and 0 <= eta <= 900))
                or (g["kind"] == "END_VALUE_AT_LEAST" and isinstance(g["params"].get("threshold"), (int, float))
                    and abs(g["params"]["threshold"]) > 2 ** 53)):
            return self.err(422, "VALIDATION_FAILED", "generic")
        if b["source_epoch"] != self.current:
            return self.err(409, "STALE_EPOCH")
        self.proposals.append(b)
        fp = f"gen:{b['source_epoch']}:{g['episode_start_media_ms']}:{g['kind'].lower()}"
        reject = None
        if not c["evidence_ids"] or any(self.ref_ms(b["source_epoch"], r) is None for r in c["evidence_ids"]):
            reject = "STALE_EVIDENCE"
        elif c["episode_fingerprint"] != fp or fp in self.used_fingerprints:
            reject = "DUPLICATE_EPISODE" if fp in self.used_fingerprints else "UNPAIRED_SIDES"
        elif (c["yes"]["label"], c["no"]["label"]) != ("Yes", "No") or \
                c["yes"]["predicate"].lower() == c["no"]["predicate"].lower():
            reject = "UNPAIRED_SIDES"
        elif c["suggested_close_in_s"] < 35:
            reject = "INSUFFICIENT_LEAD"
        if reject is None:
            self.used_fingerprints.add(fp)
        return 201, {"candidate_id": c["candidate_id"], "id": "cnd_" + uuid.uuid4().hex,
                     "status": "REJECTED" if reject else "PENDING", "reject_code": reject, "market_id": None}

    def _resolution(self, b):
        r = b["resolution"]
        self.resolutions.append(b)
        m = self.market
        out = lambda status, why=None: (201, {"resolution_id": r["resolution_id"], "id": "rsl_" + uuid.uuid4().hex,  # noqa
                                              "status": status, "reason": why})
        if m is None or m["market_id"] != r["market_id"] or m["state"] != "EVALUATING" or \
                m["rules_version"] != r["rules_version"]:
            return out("IGNORED", "STALE_MARKET")
        if b["source_epoch"] != m["lock_source_epoch"]:
            return out("IGNORED", "EPOCH_MISMATCH")
        ms = [self.ref_ms(b["source_epoch"], e) for e in r["evidence_ids"]]
        if not ms or any(x is None for x in ms):
            return out("IGNORED", "STALE_EVIDENCE")
        if r["media_interval"]["start_ms"] < m["lock_media_ms"] or min(ms) < m["lock_media_ms"]:
            return out("IGNORED", "EVIDENCE_BEFORE_LOCK")
        sup = (r["predicate_support"]["YES"], r["predicate_support"]["NO"])
        if (r["decision"] == "YES" and sup != (True, False)) or (r["decision"] == "NO" and sup != (False, True)):
            return out("IGNORED", "PREDICATE_SUPPORT_MISMATCH")
        return out("RECORDED", "WAIT") if r["decision"] == "WAIT" else out("PENDING_APPROVAL", "APPROVAL_MODE")

    def _check_common(self, b, keys):
        missing = [k for k in keys if k not in b]
        return missing

    def _epochs(self, b):
        allowed = {"schema_version", "stream_id", "source_epoch", "source_kind", "reason", "variant", "host_id",
                   "started_at_utc"}
        if set(b) - allowed or self._check_common(b, ["stream_id", "source_epoch", "source_kind", "reason",
                                                         "host_id", "started_at_utc"]):
            return self.err(422, "VALIDATION_FAILED", "fields")
        if not EP.match(b["source_epoch"]) or b["stream_id"] != self.stream_id or not UTC.match(b["started_at_utc"]):
            return self.err(422, "VALIDATION_FAILED", "format")
        if b["source_kind"] not in ("TWITCH_STREAMLINK", "TWITCH_TAB_CAPTURE", "TEST_FIXTURE"):
            return self.err(422, "VALIDATION_FAILED", "kind")
        if b["reason"] not in ("PROCESS_START", "PROCESS_RESTART", "PTS_DISCONTINUITY", "AFTER_GAP", "ADAPTER_SWITCH"):
            return self.err(422, "VALIDATION_FAILED", "reason")
        ep = b["source_epoch"]
        if ep in self.epochs:
            if ep != self.current:
                return self.err(409, "STALE_EPOCH", details={"current_source_epoch": self.current})
            return 200, {"source_epoch": ep, "created": False, "current_source_epoch": ep, "stream_session_id": "run_x"}
        self.epochs[ep] = b
        self.epoch_order.append(ep)
        self.current = ep
        return 201, {"source_epoch": ep, "created": True, "current_source_epoch": ep, "stream_session_id": "run_x",
                     "voided_market_id": None}

    def _heartbeat(self, b):
        allowed = {"schema_version", "stream_id", "source_epoch", "worker_state", "last_media_end_ms",
                   "last_input_age_ms", "asr_backlog_ms", "queue_depth", "gap_threshold_ms", "host_id", "host_wall_utc"}
        if set(b) - allowed or set(allowed) - set(b) - {"schema_version"}:
            return self.err(422, "VALIDATION_FAILED", "fields")
        if b["worker_state"] not in ("CONNECTING", "LIVE", "GAP", "STALE", "STOPPED") or not UTC.match(b["host_wall_utc"]):
            return self.err(422, "VALIDATION_FAILED", "format")
        for k in ("asr_backlog_ms", "queue_depth", "gap_threshold_ms"):
            if not isinstance(b[k], int) or b[k] < 0:
                return self.err(422, "VALIDATION_FAILED", k)
        if b["source_epoch"] is not None and b["source_epoch"] != self.current:
            return self.err(409, "STALE_EPOCH")
        self.heartbeats.append(b)
        return 200, {"server_time_utc": "2026-11-15T00:00:00.000Z", "stream_session_id": "run_x",
                     "current_source_epoch": self.current}

    def _observations(self, b):
        if set(b) - {"schema_version", "stream_id", "source_epoch", "items"} or not (1 <= len(b.get("items", [])) <= 50):
            return self.err(422, "VALIDATION_FAILED")
        if b["source_epoch"] != self.current:
            return self.err(409, "STALE_EPOCH")
        acc, dup, rej = 0, 0, []
        for it in b["items"]:
            key = (b["source_epoch"], it["sequence"])
            if key in self.observations:
                dup += 1
                continue
            ok = (isinstance(it["sequence"], int) and it["sequence"] >= 1 and UTC.match(it["captured_at_utc"])
                  and it["media_end_ms"] >= it["media_start_ms"] >= 0 and set(it["quality_flags"]) <= FLAGS
                  and it.get("source_wall_time_utc") is None)
            if it["kind"] == "FRAME":
                ok = ok and it["media_start_ms"] == it["media_end_ms"] and \
                    self.evidence_epoch.get(it.get("evidence_id")) == b["source_epoch"]
            elif it["kind"] == "TRANSCRIPT":
                ok = ok and it["transcript"] is not None and len(it["transcript"]["text"]) <= 1000
            elif it["kind"] == "GAP":
                ok = ok and it["gap"] is not None
            else:
                ok = False
            if not ok:
                rej.append({"sequence": it["sequence"], "code": "VALIDATION_FAILED"})
                continue
            self.observations[key] = it
            acc += 1
        return 200, {"accepted": acc, "duplicates": dup, "rejected": rej}

    def _evidence(self, files):
        if files is None or "meta" not in files or "file" not in files:
            return self.err(422, "VALIDATION_FAILED")
        meta, data = json.loads(files["meta"]), files["file"]
        if set(meta) != {"source_epoch", "sequence", "kind", "media_ms", "width", "height", "sha256"}:
            return self.err(422, "VALIDATION_FAILED", "meta")
        if hashlib.sha256(data).hexdigest() != meta["sha256"] or data[:3] != b"\xff\xd8\xff" or data[-2:] != b"\xff\xd9":
            return self.err(422, "VALIDATION_FAILED", "file")
        if len(data) > 300 * 1024:
            return self.err(422, "VALIDATION_FAILED", "size")
        if meta["source_epoch"] != self.current:
            return self.err(409, "STALE_EPOCH")
        key = (meta["source_epoch"], meta["sequence"])
        if key in self.evidence:
            evd, sha = self.evidence[key]
            if sha != meta["sha256"]:
                return self.err(409, "IDEMPOTENCY_CONFLICT")
            return 200, {"evidence_id": evd, "deduped": True}
        evd = "evd_" + uuid.uuid4().hex
        self.evidence[key] = (evd, meta["sha256"])
        self.evidence_epoch[evd] = meta["source_epoch"]
        self.evidence_ms[evd] = meta["media_ms"]
        return 201, {"evidence_id": evd, "deduped": False}

    def _handler(self):
        api = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                with api.lock:
                    if self.headers.get("authorization", "") != f"Bearer {api.token}":
                        status, body = api.err(401, "UNAUTHENTICATED")
                    else:
                        status, body = api.get_route(self.path)
                    api.calls.append((self.path, status))
                out = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def do_POST(self):
                n = int(self.headers.get("content-length", "0"))
                raw = self.rfile.read(n)
                auth = self.headers.get("authorization", "")
                with api.lock:
                    api.auth_headers_seen.add(auth)
                    plan = next((p for p in api.fail_plan if self.path.endswith(p[0])), None)
                    if plan:
                        api.fail_plan.remove(plan)
                    if auth != f"Bearer {api.token}":
                        status, body = api.err(401, "UNAUTHENTICATED")
                    elif plan and not plan[2]:
                        status, body = api.err(plan[1], "INTERNAL_ERROR" if plan[1] >= 500 else "RATE_LIMITED")
                    else:
                        files = None
                        if self.path.endswith("/evidence"):
                            msg = BytesParser(policy=HTTP).parsebytes(
                                b"Content-Type: " + self.headers["content-type"].encode() + b"\r\n\r\n" + raw)
                            files = {}
                            for part in msg.iter_parts():
                                name = part.get_param("name", header="content-disposition")
                                payload = part.get_payload(decode=True)
                                files[name] = payload.decode() if name == "meta" else payload
                            body_json = None
                        else:
                            body_json = json.loads(raw)
                        status, body = api.route(self.path, body_json, files)
                        if plan and plan[2]:  # committed, but the response is lost: client must retry safely
                            status, body = api.err(plan[1], "INTERNAL_ERROR")
                    api.calls.append((self.path, status))
                out = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        return H
