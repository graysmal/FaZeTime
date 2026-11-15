"""Wire models for CONTRACTS v1 (§9.13). Requests use extra="forbid" (§9.12).

Response models are also strict so the server cannot leak unplanned fields. Model validators encode
the §9.14 fixture invariants so the server checks its own receipts/events before committing them.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StringConstraints, model_validator

from .ids import UUID_PATTERN, id_pattern
from .timeutil import UTC_PATTERN

# ---- scalar types -------------------------------------------------------------------------------
Utc = Annotated[str, StringConstraints(pattern=UTC_PATTERN)]
Minor = Annotated[StrictInt, Field(ge=0, le=1_000_000_000)]
Pos = Annotated[StrictInt, Field(ge=1)]
NonNeg = Annotated[StrictInt, Field(ge=0)]
CUuid = Annotated[str, StringConstraints(pattern=UUID_PATTERN)]


def _id(prefix: str):
    return Annotated[str, StringConstraints(pattern=id_pattern(prefix))]


UserId = _id("usr")
SessionId = _id("ses")
StreamId = _id("str")
RunId = _id("run")
MarketId = _id("mkt")
WagerId = _id("wgr")
TxnId = _id("txn")
EpochId = _id("ep")
RequestId = _id("req")
InviteId = _id("inv")
EvidenceId = _id("evd")

# ---- enums (A) ----------------------------------------------------------------------------------
Side = Literal["YES", "NO"]
MarketState = Literal["DRAFT", "OPEN", "LOCKED", "EVALUATING", "SETTLED", "VOID"]
ViewerMarketState = Literal["OPEN", "LOCKED", "EVALUATING", "SETTLED", "VOID"]
VoidReason = Literal[
    "EMPTY_POOL", "ONE_SIDED_POOL", "UNRESOLVABLE", "RESOLUTION_TIMEOUT", "SOURCE_GAP", "RUN_RESET", "OPERATOR_CANCELLED"
]
MarketOrigin = Literal["OPERATOR_FIXTURE", "CANNED_FIXTURE", "AI_APPROVED", "AI_AUTOMATIC"]
WagerStatus = Literal["ACCEPTED", "WON", "LOST", "REFUNDED"]
MyResult = Literal["NONE", "PENDING", "WON", "LOST", "VOID_REFUNDED", "UNRESOLVED_REFUNDED"]
MediaHealth = Literal["CONNECTING", "LIVE", "GAP", "STALE", "STOPPED"]
SourceKind = Literal["TWITCH_STREAMLINK", "TWITCH_TAB_CAPTURE", "TEST_FIXTURE"]
AiMode = Literal["OFF", "SHADOW", "APPROVAL", "AUTOMATIC", "FIXTURE"]
PaymentMode = Literal["MOCK", "UNAVAILABLE", "STRIPE_TEST"]
Role = Literal["VIEWER", "OPERATOR", "MEDIA_WORKER", "CALL_WORKER"]
RunState = Literal["ACTIVE", "ARCHIVED"]
PauseReason = Literal["SOURCE_NOT_LIVE", "OPERATOR_PAUSE", "DRAW_BOUNDARY"]
PresenceState = Literal["PRESENT", "ABSENT"]
PageVisibility = Literal["VISIBLE", "HIDDEN", "UNKNOWN"]
PlayerState = Literal["PLAYING", "PAUSED", "BUFFERING", "UNKNOWN"]
AggregateType = Literal["STREAM", "MARKET", "WAGER", "WALLET", "SOURCE", "RAFFLE", "CALL"]
Audience = Literal["PUBLIC", "USER", "OPERATOR"]
LedgerReason = Literal[
    "SEED_GRANT", "FIXTURE_CREDIT", "WAGER_STAKE", "PAYOUT", "REFUND", "STRIPE_TEST_TOPUP", "REDEMPTION"
]
ErrorCode = Literal[
    "UNAUTHENTICATED", "FORBIDDEN", "INVALID_AMOUNT", "INSUFFICIENT_FUNDS", "MARKET_CLOSED", "STALE_MARKET",
    "WRONG_RUN", "IDEMPOTENCY_CONFLICT", "CAPABILITY_UNAVAILABLE", "SOURCE_STALE", "RATE_LIMITED",
    "VALIDATION_FAILED", "SIDE_CONFLICT", "NOT_FOUND", "INTERNAL_ERROR",
    "STALE_EPOCH",  # worker-only (§9.16); never returned on viewer routes
]
EventType = Literal[
    "stream.updated", "source.health", "market.opened", "pool.updated", "market.locked", "market.evaluating",
    "market.settled", "market.voided", "wager.updated", "wallet.changed",
]
SETTLEMENT_ALGORITHM = "PARIMUTUEL_FLOOR_REMAINDER_V1"
UNRESOLVED_REASONS = frozenset({"UNRESOLVABLE", "RESOLUTION_TIMEOUT"})


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- shared (B) ---------------------------------------------------------------------------------
class LimitsModel(Strict):
    stake_min_minor: Minor
    stake_max_minor: Minor
    stake_step_minor: Pos
    stake_default_minor: Minor
    topup_presets_minor: list[Minor]
    topup_min_minor: Minor
    topup_max_minor: Minor
    topup_step_minor: Pos


class Modes(Strict):
    ai_mode: AiMode
    payment_mode: PaymentMode
    media_source_kind: SourceKind | None


class WalletSummary(Strict):
    stream_session_id: RunId
    available_minor: Minor
    in_play_minor: Minor
    balance_version: NonNeg
    pending_topup_minor: Minor | None = None


class StreamInfo(Strict):
    stream_id: StreamId
    twitch_channel_login: str
    stream_session_id: RunId
    run_state: RunState
    aggregate_version: Pos
    wagering_paused: StrictBool
    wagering_paused_reason: PauseReason | None

    @model_validator(mode="after")
    def _pause(self):
        if self.wagering_paused != (self.wagering_paused_reason is not None):
            raise ValueError("wagering_paused_reason is set iff wagering_paused")
        return self


class SourceHealth(Strict):
    state: MediaHealth
    source_kind: SourceKind | None
    source_epoch: EpochId | None
    last_media_at_utc: Utc | None
    last_transcript_at_utc: Utc | None
    updated_at_utc: Utc


# ---- snapshot (C) -------------------------------------------------------------------------------
class Pool(Strict):
    yes_minor: Minor
    no_minor: Minor
    total_minor: Minor
    simulated_minor: Minor
    wager_count: NonNeg

    @model_validator(mode="after")
    def _totals(self):
        if self.total_minor != self.yes_minor + self.no_minor:
            raise ValueError("pool.total_minor must equal yes_minor + no_minor")
        if self.simulated_minor > self.total_minor:
            raise ValueError("pool.simulated_minor is included in totals")
        return self


class PublicMarket(Strict):
    market_id: MarketId
    stream_session_id: RunId
    rules_version: Pos
    aggregate_version: Pos
    state: ViewerMarketState  # DRAFT never appears in viewer payloads
    origin: MarketOrigin
    question: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    yes_label: Annotated[str, StringConstraints(min_length=1, max_length=40)] = "Yes"
    no_label: Annotated[str, StringConstraints(min_length=1, max_length=40)] = "No"
    opened_at_utc: Utc
    close_at_utc: Utc
    resolve_by_utc: Utc
    locked_at_utc: Utc | None
    terminal_at_utc: Utc | None
    pool: Pool
    winning_side: Side | None
    void_reason: VoidReason | None
    settlement_algorithm: str | None
    # reserved, null until P4/P5
    criteria: dict[str, Any] | None = None
    opening_evidence_ids: list[EvidenceId] | None = None
    resolution_evidence_ids: list[EvidenceId] | None = None
    resolution_mode: str | None = None
    resolution_reason: str | None = None

    @model_validator(mode="after")
    def _terminal_fields(self):
        if (self.state == "SETTLED") != (self.winning_side is not None):
            raise ValueError("winning_side is present iff SETTLED")
        if (self.state == "VOID") != (self.void_reason is not None):
            raise ValueError("void_reason is present iff VOID")
        if (self.state == "SETTLED") != (self.settlement_algorithm is not None):
            raise ValueError("settlement_algorithm is present iff SETTLED")
        if (self.state in ("SETTLED", "VOID")) != (self.terminal_at_utc is not None):
            raise ValueError("terminal_at_utc is present iff terminal")
        if self.settlement_algorithm is not None and self.settlement_algorithm != SETTLEMENT_ALGORITHM:
            raise ValueError("unknown settlement_algorithm")
        return self


class OperatorMarket(Strict):
    """Operator-only market view (§9.8, not part of the viewer contract). Superset of the PublicMarket fields;
    DRAFT is allowed and its opened/close/resolve times are null until OPEN (durations live in *_in_s)."""

    market_id: MarketId
    stream_session_id: RunId
    rules_version: Pos
    aggregate_version: Pos
    state: MarketState
    origin: MarketOrigin
    question: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    yes_label: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    no_label: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    opened_at_utc: Utc | None
    close_at_utc: Utc | None
    resolve_by_utc: Utc | None
    locked_at_utc: Utc | None
    terminal_at_utc: Utc | None
    pool: Pool
    winning_side: Side | None
    void_reason: VoidReason | None
    settlement_algorithm: str | None
    criteria: dict[str, Any] | None = None
    opening_evidence_ids: list[EvidenceId] | None = None
    resolution_evidence_ids: list[EvidenceId] | None = None
    resolution_mode: str | None = None
    resolution_reason: str | None = None
    close_in_s: Pos | None = None
    resolve_in_s: Pos | None = None
    created_at_utc: Utc | None = None

    @model_validator(mode="after")
    def _terminal_fields(self):
        if (self.state == "SETTLED") != (self.winning_side is not None):
            raise ValueError("winning_side is present iff SETTLED")
        if (self.state == "VOID") != (self.void_reason is not None):
            raise ValueError("void_reason is present iff VOID")
        if self.state != "DRAFT" and None in (self.opened_at_utc, self.close_at_utc, self.resolve_by_utc):
            raise ValueError("opened/close/resolve times are required once OPEN")
        return self


class WagerReceipt(Strict):
    schema_version: Literal[1] = 1
    wager_id: WagerId
    operation_id: CUuid
    stream_session_id: RunId
    market_id: MarketId
    rules_version: Pos
    side: Side
    amount_minor: Minor
    status: WagerStatus
    accepted_at_utc: Utc
    terminal_at_utc: Utc | None
    stake_txn_id: TxnId
    terminal_txn_id: TxnId | None
    payout_minor: Minor | None
    refund_minor: Minor | None
    market_aggregate_version: Pos
    wallet_after: WalletSummary
    replayed: StrictBool

    @model_validator(mode="after")
    def _status_fields(self):
        if (self.status == "ACCEPTED") != (self.terminal_at_utc is None):
            raise ValueError("terminal_at_utc is null iff ACCEPTED")
        if self.status == "WON" and (self.payout_minor is None or self.payout_minor < self.amount_minor):
            raise ValueError("WON payout is gross and includes the stake")
        if self.status == "LOST" and self.payout_minor != 0:
            raise ValueError("LOST payout is 0")
        if self.status == "REFUNDED" and self.refund_minor != self.amount_minor:
            raise ValueError("REFUNDED refund equals the stake")
        return self


class MyPosition(Strict):
    market_id: MarketId
    side: Side | None
    stake_total_minor: Minor
    result: MyResult
    payout_total_minor: Minor | None
    refund_total_minor: Minor | None
    wagers: list[WagerReceipt]


class StreamSnapshot(Strict):
    schema_version: Literal[1]
    server_time_utc: Utc
    event_hwm: NonNeg
    stream: StreamInfo
    modes: Modes
    limits: LimitsModel
    source_health: SourceHealth
    market: PublicMarket | None
    my_position: MyPosition | None
    wallet: WalletSummary
    raffle: None = None


# ---- wager request (D) --------------------------------------------------------------------------
class WagerRequest(Strict):
    operation_id: CUuid
    stream_session_id: RunId
    market_id: MarketId
    rules_version: Pos
    side: Side
    amount_minor: StrictInt


# ---- me (F) -------------------------------------------------------------------------------------
class MeUser(Strict):
    user_id: UserId
    display_name: Annotated[str, StringConstraints(min_length=1, max_length=32)]
    claimed_twitch_login: str | None
    role: Role


class MeSession(Strict):
    session_id: SessionId
    expires_at_utc: Utc


class MeCurrentStream(Strict):
    stream_id: StreamId
    twitch_channel_login: str
    stream_session_id: RunId


class Me(Strict):
    # Required on the top-level GET /v1/me response (the server always sends it); optional when nested in
    # EnrollResponse.me, which fixture enroll/response omits (contract finding, additive either way).
    schema_version: Literal[1] = 1
    server_time_utc: Utc
    user: MeUser
    session: MeSession
    current_stream: MeCurrentStream | None
    wallet: WalletSummary | None


# ---- errors (G) ---------------------------------------------------------------------------------
class ErrorBody(Strict):
    code: ErrorCode
    message: str
    retryable: StrictBool
    retry_after_ms: NonNeg | None
    request_id: RequestId
    operation_id: CUuid | None
    details: dict[str, Any] | None


class ErrorEnvelope(Strict):
    schema_version: Literal[1] = 1
    error: ErrorBody
    server_time_utc: Utc


# ---- events (H) ---------------------------------------------------------------------------------
class StreamPayload(Strict):
    stream: StreamInfo
    modes: Modes


_PAYLOAD_MODELS: dict[str, type[BaseModel]] = {
    "stream.updated": StreamPayload,
    "source.health": SourceHealth,
    "market.opened": PublicMarket,
    "pool.updated": PublicMarket,
    "market.locked": PublicMarket,
    "market.evaluating": PublicMarket,
    "market.settled": PublicMarket,
    "market.voided": PublicMarket,
    "wager.updated": WagerReceipt,
    "wallet.changed": WalletSummary,
}
_EVENT_AGGREGATE = {
    "stream.updated": "STREAM",
    "source.health": "SOURCE",
    "wager.updated": "WAGER",
    "wallet.changed": "WALLET",
}


class DomainEvent(Strict):
    schema_version: Literal[1]
    event_id: Pos
    stream_session_id: RunId
    aggregate_type: AggregateType
    aggregate_id: str
    aggregate_version: Pos
    event_type: EventType
    audience: Audience
    occurred_at_utc: Utc
    payload: dict[str, Any]

    @model_validator(mode="after")
    def _payload(self):
        _PAYLOAD_MODELS[self.event_type].model_validate(self.payload)
        expected = _EVENT_AGGREGATE.get(self.event_type, "MARKET")
        if self.aggregate_type != expected:
            raise ValueError(f"{self.event_type} belongs to aggregate {expected}")
        return self


def validate_event_payload(event_type: str, payload: dict[str, Any]) -> None:
    _PAYLOAD_MODELS[event_type].model_validate(payload)


class WsTicketRequest(Strict):
    stream_id: StreamId


class WsTicketResponse(Strict):
    schema_version: Literal[1]
    ticket: Annotated[str, StringConstraints(pattern=r"^fzw_[A-Za-z0-9_-]{16,}$")]
    expires_at_utc: Utc
    ws_path: Literal["/v1/ws"]


# ---- presence (I) -------------------------------------------------------------------------------
class PresenceHeartbeat(Strict):
    device_id: CUuid
    tab_instance_id: CUuid
    stream_id: StreamId
    known_stream_session_id: RunId | None = None
    observed_channel_login: Annotated[str, StringConstraints(max_length=25)] | None = None
    page_visibility: PageVisibility
    player_state: PlayerState
    extension_version: Annotated[str, StringConstraints(min_length=1, max_length=32)]


class PresenceAck(Strict):
    schema_version: Literal[1]
    server_time_utc: Utc
    last_seen_utc: Utc
    presence_state: PresenceState
    heartbeat_interval_ms: Pos
    presence_ttl_ms: Pos
    current_stream_session_id: RunId


# ---- enroll (J) ---------------------------------------------------------------------------------
class EnrollRequest(Strict):
    invite_code: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    display_name: Annotated[str, StringConstraints(min_length=1, max_length=32)]
    claimed_twitch_login: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_]{1,25}$")] | None = None
    device_id: CUuid


class EnrollResponse(Strict):
    schema_version: Literal[1]
    session_token: Annotated[str, StringConstraints(pattern=r"^fzs_[A-Za-z0-9_-]{16,}$")]
    session_id: SessionId
    expires_at_utc: Utc
    me: Me


# ---- operator requests (not part of the viewer contract; §9.8) ------------------------------------
class OpCreateInvite(Strict):
    operation_id: CUuid
    role: Literal["VIEWER", "OPERATOR"] = "VIEWER"
    is_bot: StrictBool = False
    bind_user_id: UserId | None = None


class OpCreateStream(Strict):
    operation_id: CUuid
    twitch_channel_login: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_]{1,25}$")]


class OpResetRun(Strict):
    operation_id: CUuid
    stream_id: StreamId


class OpFixtureCredit(Strict):
    operation_id: CUuid
    user_id: UserId
    amount_minor: StrictInt
    memo: Annotated[str, StringConstraints(max_length=80)] | None = None


class OpCreateMarket(Strict):
    operation_id: CUuid
    question: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    yes_label: Annotated[str, StringConstraints(min_length=1, max_length=40)] = "Yes"
    no_label: Annotated[str, StringConstraints(min_length=1, max_length=40)] = "No"
    close_in_s: Pos
    resolve_in_s: Pos


class OpMarketAction(Strict):
    operation_id: CUuid


class OpSettleMarket(Strict):
    operation_id: CUuid
    winning_side: Side
    note: Annotated[str, StringConstraints(max_length=200)] | None = None  # stored in the audit row


class OpVoidMarket(Strict):
    operation_id: CUuid
    note: Annotated[str, StringConstraints(max_length=200)] | None = None


class OpRevokeSessions(Strict):
    operation_id: CUuid
    user_id: UserId


# ---- P6 Stripe TEST-mode top-ups (§9.18) ---------------------------------------------------------
TopupId = _id("top")
TopupStatus = Literal["CREATED", "PENDING", "CREDITED", "FAILED", "EXPIRED"]


class TopupRequest(Strict):
    operation_id: CUuid
    amount_minor: StrictInt


class TopupReceipt(Strict):
    schema_version: Literal[1] = 1
    topup_id: TopupId
    operation_id: CUuid
    stream_session_id: RunId  # additive: the run this top-up credits, even after a reset (§9.5)
    amount_minor: Minor
    currency: Literal["usd"]
    status: TopupStatus
    payment_mode: PaymentMode
    checkout_url: str | None = None  # only while PENDING; open in a new tab; never log it
    checkout_expires_at_utc: Utc | None = None
    replayed: StrictBool
