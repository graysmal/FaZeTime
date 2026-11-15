"""AI proposal acceptance, operator approval and resolution handling (CONTRACTS §9.17, D32; P4/P5).

The model only proposes; this module validates and decides. Every model field (question, labels, predicates,
rationale, reason, contradictions) is untrusted data: stored verbatim, length-bounded, never interpreted and
never used to pick a code path except through the fixed checks below. Opening, settling and voiding go through
``domain`` inside one ``BEGIN IMMEDIATE`` transaction, exactly like operator fixture markets, so the existing
money invariants (escrow, single settlement, refund once, conservation) apply unchanged.

Evidence references (``evidence_ids``, §9.17 item 5c) are a frame's ``evd_<32 hex>`` ID, or a transcript observation
(keyed by (source_epoch, sequence), §9.16 item 4) written ``<source_epoch>:<sequence>`` once the API accepted it.
Anything else, including a reference into another epoch, is unknown: STALE_EVIDENCE for proposals.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import (BaseModel, Discriminator, Field, StrictBool, StrictInt, StringConstraints, Tag, ValidationError,
                      model_validator)

from . import api_operator, domain, events, source_health, timeutil, views
from .config import Settings
from .deps import Services, body_schema, operator_principal, svc_of
from .domain import Principal
from .errors import ApiError
from .ids import new_id, request_hash
from .schemas import CUuid, EpochId, MarketId, NonNeg, Pos, Strict, StreamId

log = logging.getLogger("fazetime.ai")
operator_router = APIRouter(prefix="/v1/operator", tags=["operator-ai"])

TEMPLATE_H2H = "H2H_WINNER_V1"
TEMPLATE_GENERIC = "GENERIC_BINARY_V1"  # §9.19 (D37): one yes/no question about one episode of any game
_FRAME_REF = re.compile(r"evd_[0-9a-f]{32}")
_OBS_REF = re.compile(r"(ep_[0-9a-f]{32}):([0-9]{1,18})")
CANDIDATE_BURNS = ("PENDING", "SHADOW", "OPENED", "EXPIRED")  # plus reject_code OPERATOR_REJECTED
ACTIONABLE_MODES = ("APPROVAL", "AUTOMATIC")
REJECT_CODES = ("STALE_EPOCH", "STALE_EVIDENCE", "MARKET_BUSY", "DUPLICATE_EPISODE", "UNPAIRED_SIDES",
                "SOURCE_NOT_LIVE", "INSUFFICIENT_LEAD", "AI_OFF", "OPERATOR_REJECTED")

Short = Annotated[str, StringConstraints(min_length=1, max_length=64)]
Label = Annotated[str, StringConstraints(min_length=1, max_length=40)]
Text200 = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Ref = Annotated[str, StringConstraints(min_length=1, max_length=100)]  # format checked on resolve (5c)
Refs = Annotated[list[Ref], Field(min_length=1, max_length=20)]
Seconds = Annotated[StrictInt, Field(ge=0, le=86_400)]


# ------------------------------------------------------------------------------------------------
# Wire models (§9.17). Worker requests may carry schema_version: 1 (§9.15 item 5).
# ------------------------------------------------------------------------------------------------
class SideTerms(Strict):
    label: Label
    predicate: Text200


class EpisodeOutcomeParams(Strict):
    win_verb: Literal["win", "clear", "complete", "beat", "survive", "finish"]


class EndValueParams(Strict):
    label: Label  # 1-40 chars
    threshold: StrictInt | Annotated[float, Field(strict=True, allow_inf_nan=False)]  # a JSON number, never a bool


_PHRASE_WORD = r"[A-Za-z']*[A-Za-z][A-Za-z']*"  # letters and apostrophes, at least one letter


class SayPhraseParams(Strict):
    phrase: Annotated[str, StringConstraints(max_length=80, pattern=rf"^{_PHRASE_WORD}(?: {_PHRASE_WORD}){{0,2}}$")]


class DurationParams(Strict):
    duration_s: Annotated[StrictInt, Field(ge=30, le=3600)]


GENERIC_PARAMS: dict[str, type[Strict]] = {"EPISODE_OUTCOME": EpisodeOutcomeParams,
                                           "END_VALUE_AT_LEAST": EndValueParams,
                                           "SAY_PHRASE": SayPhraseParams, "DURATION_OVER": DurationParams}
_PARAM_KEY_KIND = {key: kind for kind, model in GENERIC_PARAMS.items() for key in model.model_fields}


def _params_kind(value) -> str | None:
    """Discriminator: the one kind whose keys ``params`` uses (extra='forbid' then enforces exactly those keys)."""
    if isinstance(value, dict):
        keys = list(value)
    elif isinstance(value, BaseModel):
        keys = list(type(value).model_fields)
    else:
        return None
    kinds = {_PARAM_KEY_KIND.get(k) for k in keys}
    return kinds.pop() if len(kinds) == 1 and None not in kinds else None


GenericParams = Annotated[
    Annotated[EpisodeOutcomeParams, Tag("EPISODE_OUTCOME")] | Annotated[EndValueParams, Tag("END_VALUE_AT_LEAST")]
    | Annotated[SayPhraseParams, Tag("SAY_PHRASE")] | Annotated[DurationParams, Tag("DURATION_OVER")],
    Discriminator(_params_kind, custom_error_type="generic_params",
                  custom_error_message="params must be exactly the keys of one generic kind (§9.19)"),
]


class GenericSpec(Strict):
    """§9.19 item 1. Required for GENERIC_BINARY_V1, forbidden for H2H_WINNER_V1. Every field is required; the cues
    may be empty. The cues are untrusted model text: stored inert, shown to the operator and worker only."""

    spec_version: Literal["gen-1"]
    kind: Literal["EPISODE_OUTCOME", "END_VALUE_AT_LEAST", "SAY_PHRASE", "DURATION_OVER"]
    unit: Annotated[str, StringConstraints(min_length=1, max_length=20)]
    params: GenericParams
    episode_start_media_ms: NonNeg
    success_cue: Annotated[str, StringConstraints(max_length=160)]
    failure_cue: Annotated[str, StringConstraints(max_length=160)]

    @model_validator(mode="after")
    def _params_match_kind(self):
        expected = GENERIC_PARAMS[self.kind]
        if not isinstance(self.params, expected):
            raise ValueError(f"params must be exactly the {self.kind} keys: {sorted(expected.model_fields)}")
        return self


class Candidate(Strict):
    candidate_id: CUuid
    template_id: Literal["H2H_WINNER_V1", "GENERIC_BINARY_V1"]
    episode_fingerprint: Annotated[str, StringConstraints(min_length=3, max_length=160)]
    question: Text200
    yes: SideTerms
    no: SideTerms
    # 0-2 here; H2H needs exactly 2 (schema, below); GENERIC at most 1 (validation: UNPAIRED_SIDES, §9.19 item 2)
    subjects: Annotated[list[Label], Field(min_length=0, max_length=2)]
    evidence_ids: Refs
    announced_at_media_ms: NonNeg
    suggested_close_in_s: Seconds
    suggested_resolve_in_s: Seconds
    cancellation_conditions: Annotated[list[Text200], Field(max_length=10)] = Field(default_factory=list)
    rationale: Annotated[str, StringConstraints(max_length=300)] = ""
    model: Short
    prompt_version: Short
    generic: GenericSpec | None = None

    @model_validator(mode="after")
    def _template_shape(self):
        if self.template_id == TEMPLATE_H2H:
            if self.generic is not None:
                raise ValueError("generic is forbidden for H2H_WINNER_V1")
            if len(self.subjects) != 2:
                raise ValueError("H2H_WINNER_V1 needs exactly 2 subjects")
        elif self.generic is None:
            raise ValueError("generic is required for GENERIC_BINARY_V1")
        return self


class ProposalRequest(Strict):
    schema_version: Literal[1] = 1
    stream_id: StreamId
    source_epoch: EpochId
    candidate: Candidate


class MediaInterval(Strict):
    start_ms: NonNeg
    end_ms: NonNeg

    @model_validator(mode="after")
    def _ordered(self):
        if self.end_ms < self.start_ms:
            raise ValueError("media_interval.end_ms must be >= start_ms")
        return self


class PredicateSupport(Strict):
    YES: StrictBool
    NO: StrictBool


class Resolution(Strict):
    resolution_id: CUuid
    market_id: MarketId
    rules_version: Pos
    decision: Literal["YES", "NO", "WAIT", "UNRESOLVABLE"]
    evidence_ids: Refs
    media_interval: MediaInterval
    predicate_support: PredicateSupport
    contradictions: Annotated[list[Text200], Field(max_length=10)] = Field(default_factory=list)
    reason: Annotated[str, StringConstraints(max_length=300)] = ""
    model: Short
    prompt_version: Short


class ResolutionRequest(Strict):
    schema_version: Literal[1] = 1
    stream_id: StreamId
    source_epoch: EpochId
    resolution: Resolution


class OpApproveCandidate(Strict):
    operation_id: CUuid
    close_in_s: Pos | None = None  # optional operator override, seconds from approval, same [35, 600] rules (D39)


class OpRejectCandidate(Strict):
    operation_id: CUuid
    reason: Text200


class OpSetAiMode(Strict):
    operation_id: CUuid
    mode: Literal["OFF", "SHADOW", "APPROVAL", "AUTOMATIC"]


class OpApproveResolution(Strict):
    operation_id: CUuid


# ------------------------------------------------------------------------------------------------
# Deterministic helpers
# ------------------------------------------------------------------------------------------------
def _fmt(dt: datetime) -> str:
    return timeutil.fmt(dt)


def _dumps(value) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _norm(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", text.casefold())


def effective_mode(run: sqlite3.Row | None, settings: Settings) -> str:
    """The stored mode, except that AUTOMATIC acts as APPROVAL whenever the server flag is off (D32)."""
    mode = run["ai_mode"] if run is not None else "OFF"
    if mode == "AUTOMATIC" and not settings.allow_automatic:
        return "APPROVAL"
    return mode


def canonical_fingerprint(raw: str) -> str:
    """Lowercase, whitespace-free; an h2h fingerprint's subject pair is sorted so A|B and B|A are one episode."""
    fp = re.sub(r"\s+", "", raw.casefold())
    m = re.fullmatch(r"h2h:([^|:]+)\|([^|:]+):(.+)", fp)
    if m is None:
        return fp
    a, b = sorted((_norm(m.group(1)), _norm(m.group(2))))
    return f"h2h:{a}|{b}:{m.group(3)}"


def _first_subject(text: str, a: str, b: str) -> str | None:
    t = _norm(text)
    ia, ib = t.find(a), t.find(b)
    if ia < 0 and ib < 0:
        return None
    if ib < 0 or (0 <= ia < ib):
        return "A"
    return "B"


def sides_paired(*, question: str, subjects: list[str], yes_label: str, yes_predicate: str, no_label: str,
                 no_predicate: str, fingerprint: str) -> bool:
    """H2H_WINNER_V1: YES means subject A wins, NO means subject B wins (§9.17). Checked deterministically:
    distinct subjects; labels either the generic Yes/No pair or each naming only its own subject; each predicate
    names its own subject first; the question names subject A first; an h2h fingerprint names the same pair."""
    a, b = _norm(subjects[0]), _norm(subjects[1])
    if not a or not b or a == b or a in b or b in a:
        return False
    yl, nl = _norm(yes_label), _norm(no_label)
    if not yl or not nl or yl == nl:
        return False
    if not (yl == "yes" and nl == "no"):
        if not (a in yl and b not in yl and b in nl and a not in nl):
            return False
    if _norm(yes_predicate) == _norm(no_predicate):
        return False
    if _first_subject(yes_predicate, a, b) != "A" or _first_subject(no_predicate, a, b) != "B":
        return False
    if _first_subject(question, a, b) != "A":
        return False
    m = re.fullmatch(r"h2h:([^|:]+)\|([^|:]+):(.+)", fingerprint)
    if m is not None and {m.group(1), m.group(2)} != {a, b}:
        return False
    return True


def generic_paired(*, subjects: list[str], yes_label: str, yes_predicate: str, no_label: str, no_predicate: str,
                   generic: dict | None, fingerprint: str) -> bool:
    """GENERIC_BINARY_V1 sides check (§9.19 item 2): labels non-empty and distinct; predicates non-empty and distinct
    (compared case-insensitively, ignoring punctuation and spacing, as the H2H check does); generic.kind and its
    params valid (re-checked here because approval reads them back from storage); the canonical fingerprint starts
    with ``gen:`` and ends with ``:<kind lowercased>``; at most 1 subject."""
    yl, nl = _norm(yes_label), _norm(no_label)
    if not yl or not nl or yl == nl:
        return False
    yp, np_ = _norm(yes_predicate), _norm(no_predicate)
    if not yp or not np_ or yp == np_:
        return False
    try:
        spec = GenericSpec.model_validate(generic)
    except ValidationError:
        return False
    if not fingerprint.startswith("gen:") or not fingerprint.endswith(f":{spec.kind.lower()}"):
        return False
    return len(subjects) <= 1


def terms_paired(*, fingerprint: str, terms: dict) -> bool:
    """The §9.17 UNPAIRED_SIDES check for the candidate's template (§9.19 item 2 for GENERIC_BINARY_V1)."""
    sides = {k: terms[k] for k in ("subjects", "yes_label", "yes_predicate", "no_label", "no_predicate")}
    template, generic = terms.get("template_id", TEMPLATE_H2H), terms.get("generic")
    if template == TEMPLATE_GENERIC:
        return generic is not None and generic_paired(fingerprint=fingerprint, generic=generic, **sides)
    if template == TEMPLATE_H2H:
        return (generic is None and len(sides["subjects"]) == 2
                and sides_paired(fingerprint=fingerprint, question=terms["question"], **sides))
    return False


def _epoch_is_current(conn: sqlite3.Connection, stream_id: str, source_epoch: str) -> bool:
    row = conn.execute("SELECT stream_id, superseded_at_utc FROM source_epochs WHERE source_epoch = ?",
                       (source_epoch,)).fetchone()
    return row is not None and row["stream_id"] == stream_id and row["superseded_at_utc"] is None


def resolve_refs(conn: sqlite3.Connection, source_epoch: str, refs: list[str]) -> tuple[list[dict], bool]:
    """Resolve each ref inside ``source_epoch``. Returns (resolved, all_found). GAP observations and pruned frames
    are not usable evidence."""
    out: list[dict] = []
    seen: set[str] = set()
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        obs = _OBS_REF.fullmatch(ref)
        if _FRAME_REF.fullmatch(ref):
            row = conn.execute("SELECT * FROM evidence WHERE evidence_id = ?", (ref,)).fetchone()
            if row is None or row["source_epoch"] != source_epoch or row["file_pruned_at_utc"] is not None:
                return out, False
            out.append({"ref": ref, "kind": "FRAME", "source_epoch": source_epoch, "sequence": int(row["sequence"]),
                        "evidence_id": ref, "media_start_ms": int(row["media_ms"]), "media_end_ms": int(row["media_ms"]),
                        "received_at_utc": row["received_at_utc"]})
        elif obs is not None and obs.group(1) == source_epoch:
            row = conn.execute("SELECT * FROM observations WHERE source_epoch = ? AND sequence = ?",
                               (source_epoch, int(obs.group(2)))).fetchone()
            if row is None or row["kind"] == "GAP":
                return out, False
            out.append({"ref": ref, "kind": row["kind"], "source_epoch": source_epoch, "sequence": int(row["sequence"]),
                        "evidence_id": row["evidence_id"], "media_start_ms": int(row["media_start_ms"]),
                        "media_end_ms": int(row["media_end_ms"]), "received_at_utc": row["received_at_utc"]})
        else:  # unknown format, or an observation of another epoch (§9.17 item 5c)
            return out, False
    return out, True


def _fingerprint_used(conn: sqlite3.Connection, run_id: str, fingerprint: str, exclude_cnd: str | None) -> bool:
    placeholders = ",".join("?" for _ in CANDIDATE_BURNS)
    row = conn.execute(
        f"SELECT 1 FROM ai_candidates WHERE run_id = ? AND episode_fingerprint = ? AND cnd_id IS NOT ?"
        f" AND (status IN ({placeholders}) OR reject_code = 'OPERATOR_REJECTED') LIMIT 1",
        (run_id, fingerprint, exclude_cnd, *CANDIDATE_BURNS),
    ).fetchone()
    return row is not None


def validate_candidate(
    conn: sqlite3.Connection, *, stream_id: str, run: sqlite3.Row, source_epoch: str, evidence_ids: list[str],
    fingerprint: str, terms: dict, now: datetime, settings: Settings, exclude_cnd: str | None = None,
) -> tuple[str | None, list[dict]]:
    """The §9.17 checks, in contract order (§9.19 swaps only the sides check for GENERIC_BINARY_V1).
    Returns (reject_code or None, resolved evidence)."""
    if not _epoch_is_current(conn, stream_id, source_epoch):
        return "STALE_EPOCH", []
    refs, found = resolve_refs(conn, source_epoch, evidence_ids)
    oldest_ok = _fmt(now - timedelta(seconds=settings.evidence_fresh_s))
    if not found or any(r["received_at_utc"] < oldest_ok for r in refs):
        return "STALE_EVIDENCE", refs
    if views.nonterminal_market(conn, run["run_id"]) is not None:
        return "MARKET_BUSY", refs
    if _fingerprint_used(conn, run["run_id"], fingerprint, exclude_cnd):
        return "DUPLICATE_EPISODE", refs
    if not terms_paired(fingerprint=fingerprint, terms=terms):
        return "UNPAIRED_SIDES", refs
    if source_health.current(conn, stream_id, now, settings)["state"] != "LIVE":
        return "SOURCE_NOT_LIVE", refs
    return None, refs


def clamp_timing(close_in_s: int, resolve_in_s: int, settings: Settings) -> tuple[int | None, int]:
    """close_in_s below the minimum (or below min_lead_ms) -> None (INSUFFICIENT_LEAD); otherwise clamped."""
    resolve = min(max(resolve_in_s, settings.ai_resolve_min_s), settings.ai_resolve_max_s)
    if close_in_s < settings.ai_close_min_s or close_in_s * 1000 < settings.min_lead_ms:
        return None, resolve
    return min(close_in_s, settings.ai_close_max_s), resolve


def expire_due(conn: sqlite3.Connection, now: datetime) -> int:
    """Persist EXPIRED for PENDING candidates past expires_at_utc (status is also derived on every read)."""
    cur = conn.execute("UPDATE ai_candidates SET status = 'EXPIRED', decided_at_utc = ? WHERE status = 'PENDING'"
                       " AND expires_at_utc < ?", (_fmt(now), _fmt(now)))
    return cur.rowcount


def candidate_status(row: sqlite3.Row, now: datetime) -> str:
    if row["status"] == "PENDING" and row["expires_at_utc"] < _fmt(now):
        return "EXPIRED"
    return row["status"]


def _trace(conn: sqlite3.Connection, *, kind: str, subject_id: str, client_id: str, stream_id: str, run_id: str | None,
           market_id: str | None, source_epoch: str, model: str, prompt_version: str, evidence_ids: list[str],
           ai_mode: str, result: str, code: str | None, validation: dict, actor_kind: str, actor_ref: str | None,
           now: datetime) -> None:
    conn.execute(
        "INSERT INTO inference_traces (kind, subject_id, client_id, stream_id, run_id, market_id, source_epoch, model,"
        " prompt_version, evidence_ids_json, ai_mode, result, code, validation_json, actor_kind, actor_ref,"
        " created_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (kind, subject_id, client_id, stream_id, run_id, market_id, source_epoch, model, prompt_version,
         _dumps(list(evidence_ids)), ai_mode, result, code, _dumps(validation), actor_kind, actor_ref, _fmt(now)),
    )


def _generic_of(row: sqlite3.Row) -> dict | None:
    return json.loads(row["generic_json"]) if row["generic_json"] is not None else None


def _terms_of(row: sqlite3.Row) -> dict:
    return {"question": row["question"], "subjects": json.loads(row["subjects_json"]), "yes_label": row["yes_label"],
            "yes_predicate": row["yes_predicate"], "no_label": row["no_label"], "no_predicate": row["no_predicate"],
            "template_id": row["template_id"], "generic": _generic_of(row)}


def _proposal_hash(req: ProposalRequest) -> str:
    """§9.7 request hash. An absent generic object is left out, so H2H hashes match rows stored before §9.19."""
    payload = req.model_dump(mode="json")
    if payload["candidate"].get("generic") is None:
        payload["candidate"].pop("generic", None)
    return request_hash(payload)


def _bump_stream(conn: sqlite3.Connection, stream_id: str, now: datetime, settings: Settings) -> None:
    stream = views.get_stream(conn, stream_id)
    version = int(stream["aggregate_version"])
    cur = conn.execute("UPDATE streams SET aggregate_version = ? WHERE stream_id = ? AND aggregate_version = ?",
                       (version + 1, stream_id, version))
    if cur.rowcount != 1:
        raise domain.ConcurrentChange("stream version changed")
    events.emit_stream(conn, stream_id, now, settings)


# ------------------------------------------------------------------------------------------------
# Views
# ------------------------------------------------------------------------------------------------
def _evidence_view(conn: sqlite3.Connection, refs: list[dict]) -> list[dict]:
    out = []
    for ref in refs:
        item = dict(ref)
        item["frame_url"] = f"/v1/operator/evidence/{ref['evidence_id']}" if ref.get("evidence_id") else None
        if ref.get("kind") == "TRANSCRIPT":
            row = conn.execute("SELECT transcript_json FROM observations WHERE source_epoch = ? AND sequence = ?",
                               (ref["source_epoch"], ref["sequence"])).fetchone()
            transcript = json.loads(row["transcript_json"]) if row is not None and row["transcript_json"] else None
            item["transcript_text"] = transcript.get("text") if transcript else None
            item["untrusted"] = True
        out.append(item)
    return out


def candidate_response(row: sqlite3.Row, now: datetime, *, replayed: bool) -> dict:
    status = candidate_status(row, now)
    return {
        "schema_version": 1,
        "server_time_utc": _fmt(now),
        "candidate_id": row["candidate_id"],
        "id": row["cnd_id"],
        "status": status,
        "reject_code": row["reject_code"],
        "market_id": row["market_id"],
        "close_in_s": row["close_in_s"],
        "resolve_in_s": row["resolve_in_s"],
        "expires_at_utc": row["expires_at_utc"] if status == "PENDING" else None,
        "replayed": replayed,
    }


def candidate_view(conn: sqlite3.Connection, row: sqlite3.Row, now: datetime) -> dict:
    status = candidate_status(row, now)
    close_at = None
    if row["close_in_s"] is not None:
        close_at = _fmt(timeutil.parse(row["received_at_utc"]) + timedelta(seconds=int(row["close_in_s"])))
    return {
        "id": row["cnd_id"],
        "candidate_id": row["candidate_id"],
        "stream_session_id": row["run_id"],
        "source_epoch": row["source_epoch"],
        "status": status,
        "reject_code": row["reject_code"],
        "actionable": status == "PENDING",
        "market_id": row["market_id"],
        "template_id": row["template_id"],
        "generic": _generic_of(row),  # §9.19 item 6: the stored object (cues untrusted), null for H2H
        "episode_fingerprint": row["episode_fingerprint"],
        "question": row["question"],
        "yes": {"label": row["yes_label"], "predicate": row["yes_predicate"]},
        "no": {"label": row["no_label"], "predicate": row["no_predicate"]},
        "subjects": json.loads(row["subjects_json"]),
        "evidence_ids": json.loads(row["evidence_ids_json"]),
        "evidence": _evidence_view(conn, json.loads(row["evidence_json"])),
        "announced_at_media_ms": int(row["announced_at_media_ms"]),
        "suggested_close_in_s": int(row["suggested_close_in_s"]),
        "suggested_resolve_in_s": int(row["suggested_resolve_in_s"]),
        "close_in_s": row["close_in_s"],
        "resolve_in_s": row["resolve_in_s"],
        "proposed_close_at_utc": close_at,
        "cancellation_conditions": json.loads(row["cancellation_json"]),
        "rationale": row["rationale"],
        "rationale_untrusted": True,
        "model": row["model"],
        "prompt_version": row["prompt_version"],
        "ai_mode": row["ai_mode"],
        "received_at_utc": row["received_at_utc"],
        "expires_at_utc": row["expires_at_utc"],
        "decided_at_utc": row["decided_at_utc"],
        "decided_by_user_id": row["decided_by_user_id"],
        "decision_note": row["decision_note"],
    }


def resolution_response(row: sqlite3.Row, now: datetime, *, replayed: bool) -> dict:
    return {
        "schema_version": 1,
        "server_time_utc": _fmt(now),
        "resolution_id": row["resolution_id"],
        "id": row["rsl_id"],
        "market_id": row["market_id"],
        "status": row["status"],
        "reason": row["status_reason"],
        "replayed": replayed,
    }


def resolution_view(conn: sqlite3.Connection, row: sqlite3.Row, now: datetime) -> dict:
    market = views.get_market(conn, row["market_id"])
    actionable = (row["status"] == "PENDING_APPROVAL" and market is not None and market["state"] == "EVALUATING"
                  and _fmt(now) < market["resolve_by_utc"])
    return {
        "id": row["rsl_id"],
        "resolution_id": row["resolution_id"],
        "market_id": row["market_id"],
        "market_state": market["state"] if market is not None else None,
        "market_resolve_by_utc": market["resolve_by_utc"] if market is not None else None,
        "rules_version": int(row["rules_version"]),
        "source_epoch": row["source_epoch"],
        "decision": row["decision"],
        "status": row["status"],
        "status_reason": row["status_reason"],
        "actionable": actionable,
        "evidence_ids": json.loads(row["evidence_ids_json"]),
        "evidence": _evidence_view(conn, json.loads(row["evidence_json"])),
        "media_interval": {"start_ms": int(row["media_start_ms"]), "end_ms": int(row["media_end_ms"])},
        "predicate_support": {"YES": bool(row["support_yes"]), "NO": bool(row["support_no"])},
        "contradictions": json.loads(row["contradictions_json"]),
        "reason": row["reason"],
        "reason_untrusted": True,
        "model": row["model"],
        "prompt_version": row["prompt_version"],
        "ai_mode": row["ai_mode"],
        "received_at_utc": row["received_at_utc"],
        "decided_at_utc": row["decided_at_utc"],
        "decided_by_user_id": row["decided_by_user_id"],
    }


# ------------------------------------------------------------------------------------------------
# POST /v1/worker/proposals (called from worker.py inside a threadpool)
# ------------------------------------------------------------------------------------------------
def submit_proposal(svc: Services, req: ProposalRequest, actor_ref: str) -> tuple[dict, int]:
    settings = svc.settings
    c = req.candidate
    req_hash = _proposal_hash(req)
    fingerprint = canonical_fingerprint(c.episode_fingerprint)
    generic = c.generic.model_dump(mode="json") if c.generic is not None else None
    terms = {"question": c.question, "subjects": list(c.subjects), "yes_label": c.yes.label,
             "yes_predicate": c.yes.predicate, "no_label": c.no.label, "no_predicate": c.no.predicate,
             "template_id": c.template_id, "generic": generic}
    with svc.db.write() as conn:
        now = svc.clock.now()
        stream = views.get_stream(conn, req.stream_id)
        run = views.get_active_run(conn, req.stream_id) if stream is not None else None
        if stream is None or run is None:
            raise ApiError("NOT_FOUND", "Unknown stream.")
        existing = conn.execute("SELECT * FROM ai_candidates WHERE candidate_id = ?", (c.candidate_id,)).fetchone()
        if existing is not None:
            if existing["request_hash"] != req_hash:
                raise ApiError("IDEMPOTENCY_CONFLICT", "This candidate_id was already used for a different candidate.")
            return candidate_response(existing, now, replayed=True), 200
        expire_due(conn, now)
        mode = effective_mode(run, settings)
        code, refs = validate_candidate(conn, stream_id=req.stream_id, run=run, source_epoch=req.source_epoch,
                                        evidence_ids=list(c.evidence_ids), fingerprint=fingerprint, terms=terms,
                                        now=now, settings=settings)
        close_in_s = resolve_in_s = None
        if code is None:
            close_in_s, resolve_in_s = clamp_timing(c.suggested_close_in_s, c.suggested_resolve_in_s, settings)
            if close_in_s is None:
                code, resolve_in_s = "INSUFFICIENT_LEAD", None
        status, market_id = "REJECTED", None
        cnd_id = new_id("cnd")
        if code is None:
            if mode == "SHADOW":
                status = "SHADOW"
            elif mode == "APPROVAL":
                status = "PENDING"
            elif mode == "AUTOMATIC":
                market = domain.open_ai_market(
                    conn, run_id=run["run_id"], origin="AI_AUTOMATIC", cnd_id=cnd_id, question=c.question,
                    yes_label=c.yes.label, no_label=c.no.label,
                    criteria={"YES": c.yes.predicate, "NO": c.no.predicate},
                    cancellation=list(c.cancellation_conditions), evidence_refs=refs,
                    close_at=now + timedelta(seconds=close_in_s), resolve_in_s=resolve_in_s,
                    created_by_user_id=None, now=now, settings=settings)
                status, market_id = "OPENED", market["market_id"]
            else:  # OFF (and the P1-only FIXTURE mode): dropped, recorded for the trace
                code = "AI_OFF"
        received = _fmt(now)
        conn.execute(
            "INSERT INTO ai_candidates (cnd_id, candidate_id, request_hash, stream_id, run_id, source_epoch, template_id,"
            " episode_fingerprint, raw_fingerprint, question, yes_label, yes_predicate, no_label, no_predicate,"
            " subjects_json, evidence_ids_json, evidence_json, announced_at_media_ms, suggested_close_in_s,"
            " suggested_resolve_in_s, close_in_s, resolve_in_s, cancellation_json, rationale, model, prompt_version,"
            " ai_mode, status, reject_code, market_id, received_at_utc, expires_at_utc, decided_at_utc, generic_json)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cnd_id, c.candidate_id, req_hash, req.stream_id, run["run_id"], req.source_epoch, c.template_id,
             fingerprint, c.episode_fingerprint, c.question, c.yes.label, c.yes.predicate, c.no.label,
             c.no.predicate, _dumps(list(c.subjects)), _dumps(list(c.evidence_ids)), _dumps(refs),
             c.announced_at_media_ms, c.suggested_close_in_s, c.suggested_resolve_in_s, close_in_s, resolve_in_s,
             _dumps(list(c.cancellation_conditions)), c.rationale, c.model, c.prompt_version, mode, status, code,
             market_id, received, _fmt(now + timedelta(seconds=settings.candidate_expiry_s)),
             received if status in ("OPENED", "REJECTED") else None,
             _dumps(generic) if generic is not None else None),
        )
        _trace(conn, kind="PROPOSAL", subject_id=cnd_id, client_id=c.candidate_id, stream_id=req.stream_id,
               run_id=run["run_id"], market_id=market_id, source_epoch=req.source_epoch, model=c.model,
               prompt_version=c.prompt_version, evidence_ids=list(c.evidence_ids), ai_mode=mode, result=status,
               code=code, validation={"reject_code": code, "evidence_resolved": len(refs),
                                      "suggested_close_in_s": c.suggested_close_in_s, "close_in_s": close_in_s,
                                      "suggested_resolve_in_s": c.suggested_resolve_in_s, "resolve_in_s": resolve_in_s,
                                      "episode_fingerprint": fingerprint, "template_id": c.template_id,
                                      "generic_kind": c.generic.kind if c.generic is not None else None},
               actor_kind="WORKER", actor_ref=actor_ref, now=now)
        row = conn.execute("SELECT * FROM ai_candidates WHERE cnd_id = ?", (cnd_id,)).fetchone()
        log.info("AI candidate %s status=%s code=%s mode=%s", cnd_id, status, code, mode)
        return candidate_response(row, now, replayed=False), 201


# ------------------------------------------------------------------------------------------------
# POST /v1/worker/resolutions
# ------------------------------------------------------------------------------------------------
def _classify_resolution(conn, req: ResolutionRequest, market, mode: str, now: datetime, settings: Settings):
    """Returns (status, status_reason, resolved evidence, action) where action is None, 'SETTLE' or 'VOID'."""
    r = req.resolution
    if market is None or events.stream_id_for_run(conn, market["run_id"]) != req.stream_id:
        return "IGNORED", "UNKNOWN_MARKET", [], None
    if market["state"] in views.TERMINAL:
        return "IGNORED", "MARKET_TERMINAL", [], None
    if market["origin"] not in source_health.TWITCH_ORIGINS:
        return "IGNORED", "NOT_AI_MARKET", [], None
    if market["state"] != "EVALUATING" or int(market["rules_version"]) != r.rules_version:
        return "IGNORED", "STALE_MARKET", [], None
    if market["lock_source_epoch"] is None or req.source_epoch != market["lock_source_epoch"]:
        return "IGNORED", "EPOCH_MISMATCH", [], None
    if market["lock_media_ms"] is None:
        return "IGNORED", "NO_LOCK_POSITION", [], None
    refs, found = resolve_refs(conn, req.source_epoch, list(r.evidence_ids))
    if not found:
        return "IGNORED", "STALE_EVIDENCE", refs, None
    lock_ms = int(market["lock_media_ms"])
    if r.media_interval.start_ms < lock_ms or any(ref["media_start_ms"] < lock_ms for ref in refs):
        return "IGNORED", "EVIDENCE_BEFORE_LOCK", refs, None
    support = (r.predicate_support.YES, r.predicate_support.NO)
    if (r.decision == "YES" and support != (True, False)) or (r.decision == "NO" and support != (False, True)):
        return "IGNORED", "PREDICATE_SUPPORT_MISMATCH", refs, None
    if _fmt(now) >= market["resolve_by_utc"]:
        return "IGNORED", "DEADLINE", refs, None  # the sweeper voids with RESOLUTION_TIMEOUT
    if r.decision == "WAIT":
        return "RECORDED", "WAIT", refs, None
    if mode not in ACTIONABLE_MODES:
        return "RECORDED", "AI_OFF" if mode != "SHADOW" else "SHADOW_MODE", refs, None
    if mode == "AUTOMATIC" and r.decision == "UNRESOLVABLE":
        return "VOIDED", "UNRESOLVABLE", refs, "VOID"
    if mode == "AUTOMATIC" and not r.contradictions:
        return "SETTLED", None, refs, "SETTLE"
    reason = "CONTRADICTIONS" if mode == "AUTOMATIC" else "APPROVAL_MODE"
    duplicate = conn.execute("SELECT 1 FROM ai_resolutions WHERE market_id = ? AND decision = ?"
                             " AND status = 'PENDING_APPROVAL' LIMIT 1", (market["market_id"], r.decision)).fetchone()
    if duplicate is not None:
        return "IGNORED", "DUPLICATE", refs, None
    return "PENDING_APPROVAL", reason, refs, None


def _resolution_fields(rsl_id: str, mode: str, reason: str, refs: list[dict]) -> dict:
    return {"resolution_rsl_id": rsl_id, "resolution_mode": mode, "resolution_reason": reason or None,
            "resolution_evidence_json": _dumps(refs)}


def _supersede(conn: sqlite3.Connection, market_id: str, keep_rsl_id: str, now: datetime) -> None:
    conn.execute("UPDATE ai_resolutions SET status = 'IGNORED', status_reason = 'SUPERSEDED', decided_at_utc = ?"
                 " WHERE market_id = ? AND status = 'PENDING_APPROVAL' AND rsl_id <> ?",
                 (_fmt(now), market_id, keep_rsl_id))


def submit_resolution(svc: Services, req: ResolutionRequest, actor_ref: str) -> tuple[dict, int]:
    settings = svc.settings
    r = req.resolution
    req_hash = request_hash(req.model_dump(mode="json"))
    with svc.db.write() as conn:
        now = svc.clock.now()
        stream = views.get_stream(conn, req.stream_id)
        if stream is None:
            raise ApiError("NOT_FOUND", "Unknown stream.")
        existing = conn.execute("SELECT * FROM ai_resolutions WHERE resolution_id = ?", (r.resolution_id,)).fetchone()
        if existing is not None:
            if existing["request_hash"] != req_hash:
                raise ApiError("IDEMPOTENCY_CONFLICT", "This resolution_id was already used for a different resolution.")
            return resolution_response(existing, now, replayed=True), 200
        mode = effective_mode(views.get_active_run(conn, req.stream_id), settings)
        market = views.get_market(conn, r.market_id)
        status, reason, refs, action = _classify_resolution(conn, req, market, mode, now, settings)
        rsl_id = new_id("rsl")
        if action == "SETTLE":
            domain.settle_ai_market(conn, market_id=r.market_id, winning_side=r.decision, now=now,
                                    resolution=_resolution_fields(rsl_id, "AUTOMATIC", r.reason, refs))
        elif action == "VOID":
            domain.void_ai_unresolvable(conn, market_id=r.market_id, now=now,
                                        resolution=_resolution_fields(rsl_id, "AUTOMATIC", r.reason, refs))
        if action is not None:
            domain.pin_evidence(conn, r.market_id, refs)
        conn.execute(
            "INSERT INTO ai_resolutions (rsl_id, resolution_id, request_hash, stream_id, run_id, market_id, rules_version,"
            " source_epoch, decision, evidence_ids_json, evidence_json, media_start_ms, media_end_ms, support_yes,"
            " support_no, contradictions_json, reason, model, prompt_version, ai_mode, status, status_reason,"
            " received_at_utc, decided_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rsl_id, r.resolution_id, req_hash, req.stream_id, market["run_id"] if market is not None else None,
             r.market_id, r.rules_version, req.source_epoch, r.decision, _dumps(list(r.evidence_ids)), _dumps(refs),
             r.media_interval.start_ms, r.media_interval.end_ms, int(r.predicate_support.YES),
             int(r.predicate_support.NO), _dumps(list(r.contradictions)), r.reason, r.model, r.prompt_version, mode,
             status, reason, _fmt(now), _fmt(now) if action is not None else None),
        )
        if action is not None:
            _supersede(conn, r.market_id, rsl_id, now)
        _trace(conn, kind="RESOLUTION", subject_id=rsl_id, client_id=r.resolution_id, stream_id=req.stream_id,
               run_id=market["run_id"] if market is not None else None, market_id=r.market_id,
               source_epoch=req.source_epoch, model=r.model, prompt_version=r.prompt_version,
               evidence_ids=list(r.evidence_ids), ai_mode=mode, result=status, code=reason,
               validation={"decision": r.decision, "status_reason": reason, "evidence_resolved": len(refs),
                           "predicate_support": {"YES": r.predicate_support.YES, "NO": r.predicate_support.NO},
                           "contradictions": len(r.contradictions)},
               actor_kind="WORKER", actor_ref=actor_ref, now=now)
        row = conn.execute("SELECT * FROM ai_resolutions WHERE rsl_id = ?", (rsl_id,)).fetchone()
        log.info("AI resolution %s market=%s decision=%s status=%s reason=%s", rsl_id, r.market_id, r.decision,
                 status, reason)
        return resolution_response(row, now, replayed=False), 201


# ------------------------------------------------------------------------------------------------
# Operator routes (§9.17 items 2, 3, 5). Mutations reuse api_operator._mutation: operation_id idempotency,
# canonical request hash, audit row, all in one BEGIN IMMEDIATE transaction.
# ------------------------------------------------------------------------------------------------
def _active_run(conn) -> tuple[sqlite3.Row | None, sqlite3.Row | None]:
    stream = views.get_stream(conn)
    run = views.get_active_run(conn, stream["stream_id"]) if stream is not None else None
    return stream, run


def _get_candidate(conn, ref: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM ai_candidates WHERE cnd_id = ? OR candidate_id = ?", (ref, ref)).fetchone()
    if row is None:
        raise ApiError("NOT_FOUND", "Unknown candidate.")
    return row


def _get_resolution(conn, ref: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM ai_resolutions WHERE rsl_id = ? OR resolution_id = ?", (ref, ref)).fetchone()
    if row is None:
        raise ApiError("NOT_FOUND", "Unknown resolution.")
    return row


def _candidate_closed(row, status: str, reject_code: str | None, message: str, reason: str = "STATE") -> ApiError:
    return ApiError("MARKET_CLOSED", message, details={"state": status, "close_at_utc": None, "reason": reason,
                                                       "candidate_status": status, "reject_code": reject_code})


def _approve_error(conn, code: str, run_id: str, now: datetime, settings: Settings, stream_id: str) -> ApiError:
    """Maps a re-validation reject code to a §9.10 error; details.reject_code carries the §9.17 code."""
    if code == "STALE_EPOCH":
        state = conn.execute("SELECT current_source_epoch FROM source_state WHERE stream_id = ?", (stream_id,)).fetchone()
        return ApiError("STALE_EPOCH", "The candidate's source_epoch is no longer current.",
                        details={"reject_code": code, "current_source_epoch": state["current_source_epoch"] if state else None})
    if code == "SOURCE_NOT_LIVE":
        health = source_health.current(conn, stream_id, now, settings)
        return ApiError("SOURCE_STALE", "The Twitch source is not LIVE.",
                        details={"reject_code": code, "source_state": health["state"]})
    if code == "MARKET_BUSY":
        current = views.nonterminal_market(conn, run_id)
        return ApiError("STALE_MARKET", "Another market in this run is not terminal yet.",
                        details={"reject_code": code, "current_market_id": current["market_id"] if current else None,
                                 "current_rules_version": int(current["rules_version"]) if current else None})
    if code == "INSUFFICIENT_LEAD":
        return ApiError("MARKET_CLOSED", "Too little time would remain before close (min lead).",
                        details={"reject_code": code, "state": "PENDING", "close_at_utc": None, "reason": "DEADLINE"})
    if code == "UNPAIRED_SIDES":
        return ApiError("VALIDATION_FAILED", "Labels and predicates are not paired by side.",
                        details={"reject_code": code, "fields": [{"loc": ["candidate"], "msg": "unpaired sides"}]})
    return ApiError("STALE_MARKET", f"The candidate no longer validates ({code}).",
                    details={"reject_code": code, "current_market_id": None, "current_rules_version": None})


@operator_router.get("/candidates", responses=api_operator.ERRORS)
def list_candidates(request: Request, status: str | None = None, limit: int = 50,
                    principal: Principal = Depends(operator_principal)):
    svc: Services = svc_of(request)
    now = svc.clock.now()
    limit = max(1, min(int(limit), 200))
    with svc.db.read() as conn:
        stream, run = _active_run(conn)
        rows = conn.execute("SELECT * FROM ai_candidates WHERE run_id = ? ORDER BY received_at_utc DESC, rowid DESC"
                            " LIMIT ?", (run["run_id"], limit)).fetchall() if run is not None else []
        items = [candidate_view(conn, r, now) for r in rows]
    if status:
        items = [i for i in items if i["status"] == status.upper()]
    return JSONResponse({
        "schema_version": 1,
        "server_time_utc": _fmt(now),
        "stream_session_id": run["run_id"] if run is not None else None,
        "ai_mode": run["ai_mode"] if run is not None else None,
        "effective_ai_mode": effective_mode(run, svc.settings) if run is not None else None,
        "allow_automatic": svc.settings.allow_automatic,
        "candidate_expiry_s": svc.settings.candidate_expiry_s,
        "candidates": items,
    }, headers={"Cache-Control": "no-store"})


@operator_router.post("/candidates/{candidate_ref}/approve", openapi_extra=body_schema(OpApproveCandidate),
                      responses=api_operator.ERRORS)
async def approve_candidate(candidate_ref: str, request: Request, principal: Principal = Depends(operator_principal)):
    def handler(svc: Services, conn, req: OpApproveCandidate, now):
        settings = svc.settings
        cand = _get_candidate(conn, candidate_ref)
        stream, run = _active_run(conn)
        if run is None or cand["run_id"] != run["run_id"]:
            raise ApiError("WRONG_RUN", "That candidate belongs to an archived run.",
                           details={"current_stream_session_id": run["run_id"] if run is not None else None})
        status = candidate_status(cand, now)
        if status == "EXPIRED":
            raise _candidate_closed(cand, status, "EXPIRED", "The candidate expired before approval.", "DEADLINE")
        if status != "PENDING":
            raise _candidate_closed(cand, status, cand["reject_code"], f"The candidate is {status}, not PENDING.")
        mode = effective_mode(run, settings)
        if mode not in ACTIONABLE_MODES:
            raise ApiError("FORBIDDEN", f"AI mode is {mode}; candidates cannot be approved.", details={"ai_mode": mode})
        code, refs = validate_candidate(conn, stream_id=cand["stream_id"], run=run, source_epoch=cand["source_epoch"],
                                        evidence_ids=json.loads(cand["evidence_ids_json"]),
                                        fingerprint=cand["episode_fingerprint"], terms=_terms_of(cand), now=now,
                                        settings=settings, exclude_cnd=cand["cnd_id"])
        if code is None:
            if req.close_in_s is not None:  # operator override: seconds from now, same bounds
                close_in, _ = clamp_timing(req.close_in_s, int(cand["resolve_in_s"]), settings)
                close_at = now + timedelta(seconds=close_in) if close_in is not None else None
            else:  # the proposal's deadline stays anchored to receipt, so a slow approval cannot extend betting
                close_at = timeutil.parse(cand["received_at_utc"]) + timedelta(seconds=int(cand["close_in_s"]))
            if close_at is None or (close_at - now).total_seconds() * 1000 < max(settings.min_lead_ms, 1):
                code = "INSUFFICIENT_LEAD"
        if code is not None:
            raise _approve_error(conn, code, run["run_id"], now, settings, cand["stream_id"])
        market = domain.open_ai_market(
            conn, run_id=run["run_id"], origin="AI_APPROVED", cnd_id=cand["cnd_id"], question=cand["question"],
            yes_label=cand["yes_label"], no_label=cand["no_label"],
            criteria={"YES": cand["yes_predicate"], "NO": cand["no_predicate"]},
            cancellation=json.loads(cand["cancellation_json"]), evidence_refs=refs, close_at=close_at,
            resolve_in_s=int(cand["resolve_in_s"]), created_by_user_id=principal.user_id, now=now, settings=settings)
        cur = conn.execute("UPDATE ai_candidates SET status = 'OPENED', market_id = ?, decided_at_utc = ?,"
                           " decided_by_user_id = ? WHERE cnd_id = ? AND status = 'PENDING'",
                           (market["market_id"], _fmt(now), principal.user_id, cand["cnd_id"]))
        if cur.rowcount != 1:
            raise domain.ConcurrentChange("candidate changed concurrently")
        _trace(conn, kind="PROPOSAL_DECISION", subject_id=cand["cnd_id"], client_id=cand["candidate_id"],
               stream_id=cand["stream_id"], run_id=run["run_id"], market_id=market["market_id"],
               source_epoch=cand["source_epoch"], model=cand["model"], prompt_version=cand["prompt_version"],
               evidence_ids=json.loads(cand["evidence_ids_json"]), ai_mode=mode, result="OPENED", code=None,
               validation={"revalidated": True, "close_at_utc": _fmt(close_at), "override_close_in_s": req.close_in_s},
               actor_kind="OPERATOR", actor_ref=principal.user_id, now=now)
        row = _get_candidate(conn, cand["cnd_id"])
        body = {"candidate": candidate_view(conn, row, now), "market": views.operator_market(market)}
        return body, "AI_CANDIDATE", cand["cnd_id"], {}

    return await api_operator._mutation(request, principal, OpApproveCandidate, "OP_APPROVE_CANDIDATE", handler,
                                        path={"candidate_ref": candidate_ref}, status=200)


@operator_router.post("/candidates/{candidate_ref}/reject", openapi_extra=body_schema(OpRejectCandidate),
                      responses=api_operator.ERRORS)
async def reject_candidate(candidate_ref: str, request: Request, principal: Principal = Depends(operator_principal)):
    def handler(svc: Services, conn, req: OpRejectCandidate, now):
        cand = _get_candidate(conn, candidate_ref)
        status = candidate_status(cand, now)
        if status != "PENDING":
            raise _candidate_closed(cand, status, cand["reject_code"], f"The candidate is {status}, not PENDING.",
                                    "DEADLINE" if status == "EXPIRED" else "STATE")
        cur = conn.execute("UPDATE ai_candidates SET status = 'REJECTED', reject_code = 'OPERATOR_REJECTED',"
                           " decided_at_utc = ?, decided_by_user_id = ?, decision_note = ? WHERE cnd_id = ?"
                           " AND status = 'PENDING'", (_fmt(now), principal.user_id, req.reason, cand["cnd_id"]))
        if cur.rowcount != 1:
            raise domain.ConcurrentChange("candidate changed concurrently")
        _trace(conn, kind="PROPOSAL_DECISION", subject_id=cand["cnd_id"], client_id=cand["candidate_id"],
               stream_id=cand["stream_id"], run_id=cand["run_id"], market_id=None, source_epoch=cand["source_epoch"],
               model=cand["model"], prompt_version=cand["prompt_version"],
               evidence_ids=json.loads(cand["evidence_ids_json"]), ai_mode=cand["ai_mode"], result="REJECTED",
               code="OPERATOR_REJECTED", validation={"operator_reason": req.reason}, actor_kind="OPERATOR",
               actor_ref=principal.user_id, now=now)
        return {"candidate": candidate_view(conn, _get_candidate(conn, cand["cnd_id"]), now)}, "AI_CANDIDATE", \
            cand["cnd_id"], {}

    return await api_operator._mutation(request, principal, OpRejectCandidate, "OP_REJECT_CANDIDATE", handler,
                                        path={"candidate_ref": candidate_ref}, status=200)


@operator_router.post("/ai-mode", openapi_extra=body_schema(OpSetAiMode), responses=api_operator.ERRORS)
async def set_ai_mode(request: Request, principal: Principal = Depends(operator_principal)):
    def handler(svc: Services, conn, req: OpSetAiMode, now):
        if req.mode == "AUTOMATIC" and not svc.settings.allow_automatic:
            raise ApiError("FORBIDDEN", "AUTOMATIC mode is disabled on this server (FAZETIME_ALLOW_AUTOMATIC, D32).",
                           details={"allow_automatic": False})
        stream, run = domain.require_active_run(conn)
        previous = run["ai_mode"]
        if previous != req.mode:
            cur = conn.execute("UPDATE runs SET ai_mode = ? WHERE run_id = ? AND state = 'ACTIVE' AND ai_mode = ?",
                               (req.mode, run["run_id"], previous))
            if cur.rowcount != 1:
                raise domain.ConcurrentChange("run changed concurrently")
            _bump_stream(conn, stream["stream_id"], now, svc.settings)  # snapshot.modes.ai_mode changed
        expire_due(conn, now)
        return {"stream_session_id": run["run_id"], "ai_mode": req.mode, "previous_ai_mode": previous,
                "allow_automatic": svc.settings.allow_automatic}, "RUN", run["run_id"], {}

    return await api_operator._mutation(request, principal, OpSetAiMode, "OP_SET_AI_MODE", handler, status=200)


@operator_router.get("/resolutions", responses=api_operator.ERRORS)
def list_resolutions(request: Request, market_id: str | None = None, limit: int = 50,
                     principal: Principal = Depends(operator_principal)):
    svc: Services = svc_of(request)
    now = svc.clock.now()
    limit = max(1, min(int(limit), 200))
    with svc.db.read() as conn:
        if market_id:
            rows = conn.execute("SELECT * FROM ai_resolutions WHERE market_id = ? ORDER BY received_at_utc DESC,"
                                " rowid DESC LIMIT ?", (market_id, limit)).fetchall()
        else:
            _, run = _active_run(conn)
            rows = conn.execute("SELECT * FROM ai_resolutions WHERE run_id = ? ORDER BY received_at_utc DESC,"
                                " rowid DESC LIMIT ?", (run["run_id"], limit)).fetchall() if run is not None else []
        items = [resolution_view(conn, r, now) for r in rows]
    return JSONResponse({"schema_version": 1, "server_time_utc": _fmt(now), "market_id": market_id,
                         "resolutions": items}, headers={"Cache-Control": "no-store"})


@operator_router.post("/resolutions/{resolution_ref}/approve", openapi_extra=body_schema(OpApproveResolution),
                      responses=api_operator.ERRORS)
async def approve_resolution(resolution_ref: str, request: Request, principal: Principal = Depends(operator_principal)):
    def handler(svc: Services, conn, req: OpApproveResolution, now):
        rsl = _get_resolution(conn, resolution_ref)
        market = views.get_market(conn, rsl["market_id"])
        if market is None:
            raise ApiError("NOT_FOUND", "Unknown market.")
        if rsl["status"] != "PENDING_APPROVAL" or market["state"] in views.TERMINAL:
            raise ApiError("MARKET_CLOSED", "That suggestion is no longer awaiting approval.",
                           details={"state": market["state"], "close_at_utc": market["close_at_utc"], "reason": "STATE",
                                    "resolution_status": rsl["status"]})
        if market["state"] != "EVALUATING" or int(market["rules_version"]) != int(rsl["rules_version"]):
            raise domain._stale_market(conn, market["run_id"], "The market is not EVALUATING at that rules_version.")
        fields = _resolution_fields(rsl["rsl_id"], "OPERATOR_APPROVED", rsl["reason"], json.loads(rsl["evidence_json"]))
        if rsl["decision"] in ("YES", "NO"):
            updated = domain.settle_ai_market(conn, market_id=market["market_id"], winning_side=rsl["decision"],
                                              now=now, resolution=fields)
            new_status = "SETTLED"
        else:  # UNRESOLVABLE (WAIT is never PENDING_APPROVAL)
            run = views.get_run(conn, market["run_id"])
            if run["state"] != "ACTIVE":
                raise domain._wrong_run(conn, run)
            updated = domain.void_ai_unresolvable(conn, market_id=market["market_id"], now=now, resolution=fields)
            new_status = "VOIDED"
        domain.pin_evidence(conn, market["market_id"], json.loads(rsl["evidence_json"]))
        cur = conn.execute("UPDATE ai_resolutions SET status = ?, status_reason = 'OPERATOR_APPROVED',"
                           " decided_at_utc = ?, decided_by_user_id = ? WHERE rsl_id = ? AND status = 'PENDING_APPROVAL'",
                           (new_status, _fmt(now), principal.user_id, rsl["rsl_id"]))
        if cur.rowcount != 1:
            raise domain.ConcurrentChange("resolution changed concurrently")
        _supersede(conn, market["market_id"], rsl["rsl_id"], now)
        _trace(conn, kind="RESOLUTION_DECISION", subject_id=rsl["rsl_id"], client_id=rsl["resolution_id"],
               stream_id=rsl["stream_id"], run_id=market["run_id"], market_id=market["market_id"],
               source_epoch=rsl["source_epoch"], model=rsl["model"], prompt_version=rsl["prompt_version"],
               evidence_ids=json.loads(rsl["evidence_ids_json"]), ai_mode=rsl["ai_mode"], result=new_status,
               code="OPERATOR_APPROVED", validation={"decision": rsl["decision"]}, actor_kind="OPERATOR",
               actor_ref=principal.user_id, now=now)
        body = {"resolution": resolution_view(conn, _get_resolution(conn, rsl["rsl_id"]), now),
                "market": views.operator_market(updated)}
        return body, "AI_RESOLUTION", rsl["rsl_id"], {}

    return await api_operator._mutation(request, principal, OpApproveResolution, "OP_APPROVE_RESOLUTION", handler,
                                        path={"resolution_ref": resolution_ref}, status=200)


def pending_counts(conn, run_id: str | None, now: datetime) -> dict:
    if run_id is None:
        return {"pending_candidates": 0, "pending_resolutions": 0}
    pending = conn.execute("SELECT COUNT(*) FROM ai_candidates WHERE run_id = ? AND status = 'PENDING'"
                           " AND expires_at_utc >= ?", (run_id, _fmt(now))).fetchone()[0]
    suggestions = conn.execute("SELECT COUNT(*) FROM ai_resolutions WHERE run_id = ? AND status = 'PENDING_APPROVAL'",
                               (run_id,)).fetchone()[0]
    return {"pending_candidates": int(pending), "pending_resolutions": int(suggestions)}
