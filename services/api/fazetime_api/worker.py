"""Media-worker routes (CONTRACTS §9.16) and operator evidence routes (§9.16 item 6).

Worker input is untrusted data. It can move source health (and so void Twitch-origin markets under §9.4),
but it has no route to balances, wagers or settlement. Transcript text is stored verbatim, never parsed
as instructions. Evidence file paths are built from server-validated IDs only.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from pydantic import Field, StringConstraints, ValidationError

from . import ai, auth, domain, source_health, timeutil, views
from .deps import Services, body_schema, operator_principal, parse_body, svc_of
from .domain import Principal
from .errors import ApiError, validation_fields
from .ids import id_pattern, new_id, sha256_hex
from .schemas import EpochId, EvidenceId, MediaHealth, NonNeg, Pos, SourceKind, Strict, StreamId, Utc

log = logging.getLogger("fazetime.worker")
router = APIRouter(prefix="/v1/worker", tags=["worker"])
operator_router = APIRouter(prefix="/v1/operator", tags=["operator"])

Short = Annotated[str, StringConstraints(min_length=1, max_length=64)]
QualityFlag = Literal["PARTIAL", "CLOSED_BY_GAP", "CLOSED_BY_PTS_DISCONTINUITY", "CLOSED_BY_STOP", "AFTER_GAP",
                      "DRAINED_AFTER_STOP", "LATE_SPLIT", "PTS_UNKNOWN", "IN_DISCONTINUITY_HOLE", "LOW_CONFIDENCE",
                      "DEDUPED_OVERLAP"]
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]


class EpochRequest(Strict):
    schema_version: Literal[1] = 1
    stream_id: StreamId
    source_epoch: EpochId
    source_kind: SourceKind
    reason: Literal["PROCESS_START", "PROCESS_RESTART", "PTS_DISCONTINUITY", "AFTER_GAP", "ADAPTER_SWITCH"]
    variant: Annotated[str, StringConstraints(max_length=64)] | None = None
    host_id: Short
    started_at_utc: Utc


class HeartbeatRequest(Strict):
    schema_version: Literal[1] = 1
    stream_id: StreamId
    source_epoch: EpochId | None
    worker_state: MediaHealth
    last_media_end_ms: NonNeg | None
    last_input_age_ms: NonNeg | None
    asr_backlog_ms: NonNeg
    queue_depth: NonNeg
    gap_threshold_ms: NonNeg
    host_id: Short
    host_wall_utc: Utc


class EvidenceMeta(Strict):
    source_epoch: EpochId
    sequence: Pos
    kind: Literal["FRAME"]
    media_ms: NonNeg
    width: Annotated[int, Field(ge=1, le=8192, strict=True)]
    height: Annotated[int, Field(ge=1, le=8192, strict=True)]
    sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class TranscriptPayload(Strict):
    text: Annotated[str, StringConstraints(max_length=1000)]
    avg_logprob: FiniteFloat | None = None
    no_speech_prob: Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)] | None = None
    model: Short
    language: Annotated[str, StringConstraints(max_length=16)] | None = None


class GapPayload(Strict):
    reason: Short


class ObservationItem(Strict):
    sequence: Pos
    kind: Literal["TRANSCRIPT", "FRAME", "GAP"]
    media_start_ms: NonNeg
    media_end_ms: NonNeg
    captured_at_utc: Utc
    source_wall_time_utc: None = None  # reserved until verified against an OBS clock (D29)
    quality_flags: list[QualityFlag] = Field(default_factory=list, max_length=11)
    transcript: TranscriptPayload | None = None
    evidence_id: EvidenceId | None = None
    gap: GapPayload | None = None


class ObservationsRequest(Strict):
    schema_version: Literal[1] = 1
    stream_id: StreamId
    source_epoch: EpochId
    items: Annotated[list[ObservationItem], Field(min_length=1, max_length=50)]


@dataclass(frozen=True)
class WorkerPrincipal:
    credential_id: int
    role: str
    label: str


def credential_principal(request: Request, role: str) -> WorkerPrincipal:
    """fzk_ worker tokens of exactly ``role`` (MEDIA_WORKER or CALL_WORKER). A valid fzk_ token of the other role,
    or a valid viewer/operator session, is FORBIDDEN; anything else (missing, unknown, revoked) is 401."""
    svc: Services = svc_of(request)
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token or len(token) > 128:
        raise ApiError("UNAUTHENTICATED", "Missing worker bearer token.")
    with svc.db.read() as conn:
        if token.startswith("fzk_"):
            row = conn.execute(
                "SELECT credential_id, role, label FROM worker_credentials WHERE token_hash = ? AND revoked_at_utc IS NULL",
                (sha256_hex(token),),
            ).fetchone()
            if row is None:
                raise ApiError("UNAUTHENTICATED", "Worker token is invalid or revoked.")
            if row["role"] != role:
                raise ApiError("FORBIDDEN", f"{role} role required.")
            return WorkerPrincipal(int(row["credential_id"]), row["role"], row["label"])
        session = auth.authenticate(conn, token, svc.clock.now())
    if session is None:
        raise ApiError("UNAUTHENTICATED", "Worker token is invalid or revoked.")
    raise ApiError("FORBIDDEN", f"{role} role required.")


def worker_principal(request: Request) -> WorkerPrincipal:
    """MEDIA_WORKER fzk_ tokens only. A valid viewer/operator session is FORBIDDEN, anything else 401."""
    return credential_principal(request, "MEDIA_WORKER")


def _stream_and_run(conn, stream_id: str):
    stream = views.get_stream(conn, stream_id)
    run = views.get_active_run(conn, stream_id) if stream is not None else None
    if stream is None or run is None:
        raise ApiError("NOT_FOUND", "Unknown stream.")
    return stream, run


def _require_current_epoch(conn, stream_id: str, source_epoch: str) -> sqlite3.Row:
    epoch = conn.execute("SELECT * FROM source_epochs WHERE source_epoch = ?", (source_epoch,)).fetchone()
    if epoch is None or epoch["stream_id"] != stream_id or epoch["superseded_at_utc"] is not None:
        state = conn.execute("SELECT current_source_epoch FROM source_state WHERE stream_id = ?", (stream_id,)).fetchone()
        raise ApiError("STALE_EPOCH", "That source_epoch is not the stream's current epoch.",
                       details={"current_source_epoch": state["current_source_epoch"] if state else None})
    return epoch



def _void_twitch_market_if_unhealthy(conn, run, now, settings) -> str | None:
    market = views.nonterminal_market(conn, run["run_id"])
    if market is not None and domain.source_gap_if_needed(conn, market["market_id"], now, settings):
        return market["market_id"]
    return None


def evidence_path(settings, source_epoch: str, evidence_id: str) -> Path:
    if not re.fullmatch(id_pattern("ep"), source_epoch) or not re.fullmatch(id_pattern("evd"), evidence_id):
        raise ValueError("invalid evidence identifiers")
    return Path(settings.evidence_dir) / source_epoch / f"{evidence_id}.jpg"


def prune_evidence(conn, settings, now) -> list[Path]:
    """Keep the newest N frames that are also younger than the window, plus market-pinned frames.
    Returns file paths to delete AFTER the caller commits."""
    cutoff = timeutil.fmt(now - timedelta(seconds=settings.evidence_keep_s))
    rows = conn.execute(
        "SELECT evidence_id, source_epoch FROM evidence WHERE file_pruned_at_utc IS NULL AND pinned_by_market_id IS NULL"
        " AND (received_at_utc < ? OR evidence_id NOT IN (SELECT evidence_id FROM evidence"
        "      WHERE file_pruned_at_utc IS NULL ORDER BY received_at_utc DESC, rowid DESC LIMIT ?))",
        (cutoff, settings.evidence_keep_frames),
    ).fetchall()
    paths = []
    for row in rows:
        conn.execute("UPDATE evidence SET file_pruned_at_utc = ? WHERE evidence_id = ?",
                     (timeutil.fmt(now), row["evidence_id"]))
        paths.append(evidence_path(settings, row["source_epoch"], row["evidence_id"]))
    return paths


def delete_files(paths: list[Path]) -> None:
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            log.warning("could not delete pruned evidence file %s", path.name)


@router.post("/epochs", openapi_extra=body_schema(EpochRequest))
async def register_epoch(request: Request, worker: WorkerPrincipal = Depends(worker_principal)):
    svc: Services = svc_of(request)
    req = await parse_body(request, EpochRequest, max_bytes=svc.settings.worker_json_max_bytes)

    def work():
        with svc.db.write() as conn:
            now = svc.clock.now()
            _, run = _stream_and_run(conn, req.stream_id)
            source_health.ensure_state(conn, req.stream_id)
            existing = conn.execute("SELECT * FROM source_epochs WHERE source_epoch = ?", (req.source_epoch,)).fetchone()
            voided = None
            if existing is not None:
                if existing["stream_id"] != req.stream_id or existing["superseded_at_utc"] is not None:
                    _require_current_epoch(conn, req.stream_id, req.source_epoch)  # raises STALE_EPOCH
                created = False
            else:
                now_s = timeutil.fmt(now)
                conn.execute("UPDATE source_epochs SET superseded_at_utc = ? WHERE stream_id = ? AND superseded_at_utc IS NULL",
                             (now_s, req.stream_id))
                conn.execute(
                    "INSERT INTO source_epochs (source_epoch, stream_id, source_kind, reason, variant, host_id,"
                    " started_at_utc, registered_at_utc, credential_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (req.source_epoch, req.stream_id, req.source_kind, req.reason, req.variant, req.host_id,
                     req.started_at_utc, now_s, worker.credential_id),
                )
                conn.execute(
                    "UPDATE source_state SET current_source_epoch = ?, heartbeat_epoch = NULL, last_media_end_ms = NULL,"
                    " last_media_advanced_at_utc = NULL, last_transcript_at_utc = NULL WHERE stream_id = ?",
                    (req.source_epoch, req.stream_id),
                )
                market = views.nonterminal_market(conn, run["run_id"])
                if market is not None and market["origin"] in source_health.TWITCH_ORIGINS:
                    domain._void_market(conn, market, "SOURCE_GAP", now)  # epoch change (§9.4)
                    voided = market["market_id"]
                created = True
            source_health.refresh(conn, req.stream_id, now, svc.settings)
            return {
                "schema_version": 1,
                "server_time_utc": timeutil.fmt(now),
                "source_epoch": req.source_epoch,
                "created": created,
                "current_source_epoch": req.source_epoch,
                "stream_session_id": run["run_id"],
                "voided_market_id": voided,
            }, created

    body, created = await run_in_threadpool(work)
    svc.hub.notify()
    return JSONResponse(body, status_code=201 if created else 200)


@router.post("/heartbeat", openapi_extra=body_schema(HeartbeatRequest))
async def heartbeat(request: Request, worker: WorkerPrincipal = Depends(worker_principal)):
    svc: Services = svc_of(request)
    req = await parse_body(request, HeartbeatRequest, max_bytes=svc.settings.worker_json_max_bytes)

    def work():
        with svc.db.write() as conn:
            now = svc.clock.now()
            now_s = timeutil.fmt(now)
            _, run = _stream_and_run(conn, req.stream_id)
            source_health.ensure_state(conn, req.stream_id)
            if req.source_epoch is not None:
                _require_current_epoch(conn, req.stream_id, req.source_epoch)
            st = conn.execute("SELECT * FROM source_state WHERE stream_id = ?", (req.stream_id,)).fetchone()
            media_end, advanced_at = st["last_media_end_ms"], st["last_media_advanced_at_utc"]
            is_current = req.source_epoch is not None and req.source_epoch == st["current_source_epoch"]
            if is_current and req.last_media_end_ms is not None and (media_end is None or req.last_media_end_ms > media_end):
                media_end, advanced_at = req.last_media_end_ms, now_s  # media positions only move forward
            conn.execute(
                "UPDATE source_state SET last_heartbeat_at_utc = ?, worker_state = ?, heartbeat_epoch = ?,"
                " last_media_end_ms = ?, last_media_advanced_at_utc = ?, last_input_age_ms = ?, asr_backlog_ms = ?,"
                " queue_depth = ?, gap_threshold_ms = ?, host_id = ?, host_wall_utc = ? WHERE stream_id = ?",
                (now_s, req.worker_state, req.source_epoch, media_end, advanced_at, req.last_input_age_ms,
                 req.asr_backlog_ms, req.queue_depth, req.gap_threshold_ms, req.host_id, req.host_wall_utc,
                 req.stream_id),
            )
            if is_current and req.worker_state == "GAP":
                conn.execute("UPDATE source_epochs SET gap_reported_at_utc = ? WHERE source_epoch = ?"
                             " AND gap_reported_at_utc IS NULL", (now_s, req.source_epoch))
            source_health.refresh(conn, req.stream_id, now, svc.settings)
            _void_twitch_market_if_unhealthy(conn, run, now, svc.settings)
            state = conn.execute("SELECT current_source_epoch FROM source_state WHERE stream_id = ?",
                                 (req.stream_id,)).fetchone()
            return {"schema_version": 1, "server_time_utc": now_s, "stream_session_id": run["run_id"],
                    "current_source_epoch": state["current_source_epoch"]}

    body = await run_in_threadpool(work)
    svc.hub.notify()
    return JSONResponse(body)


@router.post("/evidence")
async def upload_evidence(request: Request, worker: WorkerPrincipal = Depends(worker_principal)):
    svc: Services = svc_of(request)
    limit = svc.settings.evidence_max_bytes
    length = request.headers.get("content-length", "")
    if not length.isdigit():
        raise ApiError("VALIDATION_FAILED", "Content-Length is required for evidence uploads.")
    if int(length) > limit + 16 * 1024:
        raise ApiError("VALIDATION_FAILED", f"Upload exceeds {limit} bytes.",
                       details={"fields": [{"loc": ["body", "file"], "msg": f"at most {limit} bytes"}]})
    if not request.headers.get("content-type", "").startswith("multipart/form-data"):
        raise ApiError("VALIDATION_FAILED", "Evidence must be multipart/form-data with parts meta and file.")
    try:
        form = await request.form(max_files=1, max_fields=1, max_part_size=limit + 1024)
    except Exception:
        raise ApiError("VALIDATION_FAILED", "Malformed multipart body.")
    meta_raw, upload = form.get("meta"), form.get("file")
    if not isinstance(meta_raw, str) or upload is None or isinstance(upload, str):
        raise ApiError("VALIDATION_FAILED", "Parts 'meta' (JSON) and 'file' (JPEG) are required.")
    try:
        meta = EvidenceMeta.model_validate_json(meta_raw)
    except ValidationError as exc:
        errors = [{**e, "loc": ("body", "meta", *e.get("loc", ()))} for e in exc.errors(include_url=False, include_input=False)]
        raise ApiError("VALIDATION_FAILED", "Invalid evidence meta.", details={"fields": validation_fields(errors)})
    data = await upload.read(limit + 1)
    await form.close()
    problems = []
    if len(data) == 0 or len(data) > limit:
        problems.append({"loc": ["body", "file"], "msg": f"JPEG must be 1..{limit} bytes"})
    elif not (data[:3] == b"\xff\xd8\xff" and data[-2:] == b"\xff\xd9"):
        problems.append({"loc": ["body", "file"], "msg": "not a JPEG (SOI/EOI markers)"})
    elif hashlib.sha256(data).hexdigest() != meta.sha256:
        problems.append({"loc": ["body", "meta", "sha256"], "msg": "sha256 does not match the file"})
    if problems:
        raise ApiError("VALIDATION_FAILED", "Invalid evidence file.", details={"fields": problems})

    def work():
        evidence_id = new_id("evd")
        final = evidence_path(svc.settings, meta.source_epoch, evidence_id)
        tmp = final.with_suffix(".tmp")
        with svc.db.write() as conn:
            now = svc.clock.now()
            epoch = _require_current_epoch(conn, epoch_stream(conn, meta.source_epoch), meta.source_epoch)
            existing = conn.execute("SELECT evidence_id, sha256 FROM evidence WHERE source_epoch = ? AND sequence = ?",
                                    (meta.source_epoch, meta.sequence)).fetchone()
            if existing is not None:
                if existing["sha256"] != meta.sha256:
                    raise ApiError("IDEMPOTENCY_CONFLICT", "That (source_epoch, sequence) already holds a different frame.")
                return {"schema_version": 1, "evidence_id": existing["evidence_id"], "deduped": True}, []
            final.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(data)
            os.replace(tmp, final)  # file exists before the row commits; no row ever points at nothing
            conn.execute(
                "INSERT INTO evidence (evidence_id, stream_id, source_epoch, sequence, kind, media_ms, width, height,"
                " sha256, byte_size, received_at_utc) VALUES (?, ?, ?, ?, 'FRAME', ?, ?, ?, ?, ?, ?)",
                (evidence_id, epoch["stream_id"], meta.source_epoch, meta.sequence, meta.media_ms, meta.width,
                 meta.height, meta.sha256, len(data), timeutil.fmt(now)),
            )
            doomed = prune_evidence(conn, svc.settings, now)
        return {"schema_version": 1, "evidence_id": evidence_id, "deduped": False}, doomed

    body, doomed = await run_in_threadpool(work)
    delete_files(doomed)
    return JSONResponse(body, status_code=200 if body["deduped"] else 201)


def epoch_stream(conn, source_epoch: str) -> str:
    row = conn.execute("SELECT stream_id FROM source_epochs WHERE source_epoch = ?", (source_epoch,)).fetchone()
    if row is None:
        raise ApiError("STALE_EPOCH", "Unknown source_epoch.", details={"current_source_epoch": None})
    return row["stream_id"]


def _item_problem(conn, source_epoch: str, item: ObservationItem) -> str | None:
    if item.media_end_ms < item.media_start_ms:
        return "VALIDATION_FAILED"
    if item.kind == "FRAME":
        if item.evidence_id is None or item.media_start_ms != item.media_end_ms or item.transcript or item.gap:
            return "VALIDATION_FAILED"
        row = conn.execute("SELECT source_epoch FROM evidence WHERE evidence_id = ?", (item.evidence_id,)).fetchone()
        if row is None or row["source_epoch"] != source_epoch:
            return "NOT_FOUND"
    elif item.kind == "TRANSCRIPT":
        if item.transcript is None or item.gap or item.evidence_id:
            return "VALIDATION_FAILED"
    elif item.gap is None or item.transcript or item.evidence_id:  # GAP
        return "VALIDATION_FAILED"
    return None


@router.post("/observations", openapi_extra=body_schema(ObservationsRequest))
async def post_observations(request: Request, worker: WorkerPrincipal = Depends(worker_principal)):
    svc: Services = svc_of(request)
    req = await parse_body(request, ObservationsRequest, max_bytes=svc.settings.worker_json_max_bytes)

    def work():
        with svc.db.write() as conn:
            now = svc.clock.now()
            now_s = timeutil.fmt(now)
            _, run = _stream_and_run(conn, req.stream_id)
            _require_current_epoch(conn, req.stream_id, req.source_epoch)
            accepted, duplicates, rejected, transcript_seen = 0, 0, [], False
            for item in req.items:
                if conn.execute("SELECT 1 FROM observations WHERE source_epoch = ? AND sequence = ?",
                                (req.source_epoch, item.sequence)).fetchone() is not None:
                    duplicates += 1
                    continue
                problem = _item_problem(conn, req.source_epoch, item)
                if problem is not None:
                    rejected.append({"sequence": item.sequence, "code": problem})
                    continue
                conn.execute(
                    "INSERT INTO observations (source_epoch, sequence, stream_id, kind, media_start_ms, media_end_ms,"
                    " captured_at_utc, received_at_utc, quality_flags_json, transcript_json, evidence_id, gap_reason)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (req.source_epoch, item.sequence, req.stream_id, item.kind, item.media_start_ms, item.media_end_ms,
                     item.captured_at_utc, now_s, json.dumps(item.quality_flags),
                     json.dumps(item.transcript.model_dump()) if item.transcript else None,
                     item.evidence_id, item.gap.reason if item.gap else None),
                )
                accepted += 1
                if item.kind == "TRANSCRIPT":
                    transcript_seen = True
                elif item.kind == "GAP":
                    conn.execute("UPDATE source_epochs SET gap_reported_at_utc = ? WHERE source_epoch = ?"
                                 " AND gap_reported_at_utc IS NULL", (now_s, req.source_epoch))
            if transcript_seen:
                conn.execute("UPDATE source_state SET last_transcript_at_utc = ? WHERE stream_id = ?",
                             (now_s, req.stream_id))
            source_health.refresh(conn, req.stream_id, now, svc.settings)
            _void_twitch_market_if_unhealthy(conn, run, now, svc.settings)
            return {"schema_version": 1, "server_time_utc": now_s, "accepted": accepted, "duplicates": duplicates,
                    "rejected": rejected}

    body = await run_in_threadpool(work)
    svc.hub.notify()
    return JSONResponse(body)


@router.post("/proposals", openapi_extra=body_schema(ai.ProposalRequest))
async def post_proposal(request: Request, worker: WorkerPrincipal = Depends(worker_principal)):
    """§9.17 item 1. 201 when the candidate is first recorded (any status, REJECTED included), 200 on a replay."""
    svc: Services = svc_of(request)
    req = await parse_body(request, ai.ProposalRequest, max_bytes=svc.settings.worker_json_max_bytes)
    body, status = await run_in_threadpool(ai.submit_proposal, svc, req, str(worker.credential_id))
    svc.hub.notify()
    return JSONResponse(body, status_code=status)


WORKER_MARKET_FIELDS = ("market_id", "rules_version", "state", "origin", "question", "yes_label", "no_label",
                        "close_at_utc", "resolve_by_utc", "lock_source_epoch", "lock_media_ms")


@router.get("/market")
def worker_market(request: Request, stream_id: str, worker: WorkerPrincipal = Depends(worker_principal)):
    """§9.17 item 5b: the run's nonterminal market (exactly these fields), or null. No balances, no user data.
    §9.19 item 6 adds template_id and generic from the market's originating candidate; both null for fixture and
    manual markets."""
    svc: Services = svc_of(request)
    with svc.db.read() as conn:
        _, run = _stream_and_run(conn, stream_id)
        row = views.nonterminal_market(conn, run["run_id"])
        market = None
        if row is not None:
            market = {k: row[k] for k in WORKER_MARKET_FIELDS}
            cand = conn.execute("SELECT template_id, generic_json FROM ai_candidates WHERE market_id = ?",
                                (row["market_id"],)).fetchone()
            market["template_id"] = cand["template_id"] if cand is not None else None
            market["generic"] = (json.loads(cand["generic_json"])
                                 if cand is not None and cand["generic_json"] is not None else None)
    return JSONResponse({"schema_version": 1, "market": market}, headers={"Cache-Control": "no-store"})


@router.post("/resolutions", openapi_extra=body_schema(ai.ResolutionRequest))
async def post_resolution(request: Request, worker: WorkerPrincipal = Depends(worker_principal)):
    """§9.17 item 4. 201 when first recorded (IGNORED included), 200 on a replay of the same resolution_id."""
    svc: Services = svc_of(request)
    req = await parse_body(request, ai.ResolutionRequest, max_bytes=svc.settings.worker_json_max_bytes)
    body, status = await run_in_threadpool(ai.submit_resolution, svc, req, str(worker.credential_id))
    svc.hub.notify()
    return JSONResponse(body, status_code=status)


@operator_router.get("/evidence")
def list_evidence(request: Request, since: str | None = None, limit: int = 200,
                  principal: Principal = Depends(operator_principal)):
    svc: Services = svc_of(request)
    now = svc.clock.now()
    if since is not None:
        try:
            timeutil.parse(since)
        except ValueError:
            raise ApiError("VALIDATION_FAILED", "since must be a canonical UTC timestamp.",
                           details={"fields": [{"loc": ["query", "since"], "msg": "expected YYYY-MM-DDTHH:MM:SS.mmmZ"}]})
    since = since or timeutil.fmt(now - timedelta(minutes=5))
    limit = max(1, min(int(limit), 500))
    with svc.db.read() as conn:
        stream = views.get_stream(conn)
        obs = conn.execute("SELECT * FROM observations WHERE received_at_utc > ? ORDER BY received_at_utc, rowid LIMIT ?",
                           (since, limit)).fetchall()
        frames = conn.execute("SELECT * FROM evidence WHERE received_at_utc > ? ORDER BY received_at_utc, rowid LIMIT ?",
                              (since, limit)).fetchall()
        health = source_health.current(conn, stream["stream_id"], now, svc.settings) if stream is not None else None
    return JSONResponse({
        "schema_version": 1,
        "server_time_utc": timeutil.fmt(now),
        "since": since,
        "source_health": health,
        "observations": [
            {k: r[k] for k in ("source_epoch", "sequence", "kind", "media_start_ms", "media_end_ms", "captured_at_utc",
                               "received_at_utc", "evidence_id", "gap_reason")}
            | {"quality_flags": json.loads(r["quality_flags_json"]),
               "transcript": json.loads(r["transcript_json"]) if r["transcript_json"] else None,
               "untrusted": True}
            for r in obs
        ],
        "frames": [
            {k: r[k] for k in ("evidence_id", "source_epoch", "sequence", "media_ms", "width", "height", "sha256",
                               "byte_size", "received_at_utc", "pinned_by_market_id", "file_pruned_at_utc")}
            for r in frames
        ],
    })


@operator_router.get("/evidence/{evidence_id}")
def get_evidence(evidence_id: str, request: Request, principal: Principal = Depends(operator_principal)):
    svc: Services = svc_of(request)
    with svc.db.read() as conn:
        row = conn.execute("SELECT source_epoch, file_pruned_at_utc FROM evidence WHERE evidence_id = ?",
                           (evidence_id,)).fetchone()
    if row is None or row["file_pruned_at_utc"] is not None:
        raise ApiError("NOT_FOUND", "Unknown or pruned evidence.")
    try:
        data = evidence_path(svc.settings, row["source_epoch"], evidence_id).read_bytes()
    except (ValueError, FileNotFoundError):
        raise ApiError("NOT_FOUND", "Evidence file is missing.")
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store",
                                                            "X-Content-Type-Options": "nosniff"})
