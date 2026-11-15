// Operator-only response shapes (CONTRACTS §9.8: operator routes are not part of the viewer contract).
// Mirrors services/api/fazetime_api/api_operator.py and worker.py. Shared enums and viewer shapes come from
// @fazetime/contracts. Every field is untrusted input to the UI: render text as text, never as HTML.
import type {
  AiMode,
  EnrollResponse,
  MarketOrigin,
  MarketState,
  MediaHealth,
  Modes,
  Pool,
  Role,
  RunState,
  Side,
  SourceHealth,
  StreamInfo,
  VoidReason,
} from '@fazetime/contracts';

export type { EnrollResponse, Modes };

/** views.operator_market: PublicMarket fields (DRAFT allowed, times null until OPEN) plus draft durations. */
export interface OperatorMarket {
  market_id: string;
  stream_session_id: string;
  rules_version: number;
  aggregate_version: number;
  state: MarketState;
  origin: MarketOrigin;
  question: string;
  yes_label: string;
  no_label: string;
  opened_at_utc: string | null;
  close_at_utc: string | null;
  resolve_by_utc: string | null;
  locked_at_utc: string | null;
  terminal_at_utc: string | null;
  pool: Pool;
  winning_side: Side | null;
  void_reason: VoidReason | null;
  settlement_algorithm: string | null;
  close_in_s: number;
  resolve_in_s: number;
  created_at_utc: string;
}

export interface Reconciliation {
  ok: boolean;
  accounts_checked: number;
  transactions_checked: number;
  markets_checked: number;
  problems: string[];
}

export interface RunRow {
  run_id: string;
  stream_id: string;
  state: RunState;
  ai_mode: AiMode;
  seed_grant_minor: number;
  created_at_utc: string;
  archived_at_utc: string | null;
}

export interface WalletRow {
  user_id: string;
  display_name: string;
  role: Role;
  is_bot: boolean;
  available_minor: number;
  in_play_minor: number;
  balance_version: number;
}

/** Operator health may grow worker detail later (asr_backlog_ms etc.); read it only if present. */
export type OperatorSourceHealth = SourceHealth & {
  asr_backlog_ms?: number | null;
  queue_depth?: number | null;
  last_heartbeat_at_utc?: string | null;
  heartbeat_age_ms?: number | null;
  host_id?: string | null;
};

export interface OperatorHealth {
  schema_version: 1;
  server_time_utc: string;
  service: {
    process_started_at_utc: string;
    sqlite_version: string;
    mode_labels: string[];
  };
  sweeper: { enabled: boolean; runs: number; errors: number; last_run_at_utc: string | null };
  websocket: { subscribers: number };
  event_hwm: number;
  stream: StreamInfo | null;
  run: RunRow | null;
  source_health: OperatorSourceHealth | null;
  markets: OperatorMarket[];
  wallets: WalletRow[];
  funding_source_minor: number | null;
  presence: { present_users: number; ttl_ms: number; users: unknown[] } | null;
  reconciliation: Reconciliation;
  counts: { users: number; runs: number; archived_runs: number };
  /** Present on newer APIs (P4/P5 backend); the console falls back to the snapshot for modes. */
  modes?: Modes;
  ai?: HealthAi;
  market_limits?: MarketLimits;
}

/** Common receipt fields of every operator mutation (api_operator._mutation). */
export interface OperatorReceipt {
  schema_version: 1;
  operation_id: string;
  replayed: boolean;
}

export interface MarketReceipt extends OperatorReceipt {
  market: OperatorMarket;
}

export interface InviteReceipt extends OperatorReceipt {
  invite: { invite_id: string; role: 'VIEWER' | 'OPERATOR'; is_bot: boolean; bind_user_id: string | null; expires_at_utc: string };
  /** Present only on the first response; a replay returns null (shown once, never stored). */
  invite_code: string | null;
  invite_code_note?: string;
}

export interface StreamReceipt extends OperatorReceipt {
  created: boolean;
  stream: StreamInfo;
}

export interface ResetReceipt extends OperatorReceipt {
  archived_stream_session_id: string;
  stream_session_id: string;
  voided_market_id: string | null;
  stream: StreamInfo;
}

// ---- §9.16 item 6 operator evidence --------------------------------------------------------------

export interface EvidenceObservation {
  source_epoch: string;
  sequence: number;
  kind: 'TRANSCRIPT' | 'FRAME' | 'GAP' | string;
  media_start_ms: number;
  media_end_ms: number;
  captured_at_utc: string;
  received_at_utc: string;
  evidence_id: string | null;
  gap_reason: string | null;
  quality_flags: string[];
  transcript: { text: string; model?: string; language?: string | null; avg_logprob?: number | null; no_speech_prob?: number | null } | null;
  untrusted: true;
}

export interface EvidenceFrame {
  evidence_id: string;
  source_epoch: string;
  sequence: number;
  media_ms: number;
  width: number;
  height: number;
  sha256: string;
  byte_size: number;
  received_at_utc: string;
  pinned_by_market_id: string | null;
  file_pruned_at_utc: string | null;
}

export interface EvidenceList {
  schema_version: 1;
  server_time_utc: string;
  since: string;
  source_health: SourceHealth | null;
  observations: EvidenceObservation[];
  frames: EvidenceFrame[];
}

export type { MediaHealth };

// ---- §9.17 supervised AI (operator side) -------------------------------------------------------------

export const AI_MODE_CHOICES = ['OFF', 'SHADOW', 'APPROVAL', 'AUTOMATIC'] as const;
export type AiModeChoice = (typeof AI_MODE_CHOICES)[number];

export interface HealthAi {
  ai_mode: string;
  effective_ai_mode: string;
  allow_automatic: boolean;
  pending_candidates: number;
  pending_resolutions: number;
}

export interface MarketLimits {
  min_lead_ms: number;
  ai_close_in_s?: { min: number; max: number };
  ai_resolve_in_s?: { min: number; max: number };
  candidate_expiry_s?: number;
  evidence_fresh_s?: number;
}

/** A cited evidence reference as the API resolved it (§9.17 item 5c). Text fields are untrusted. */
export interface AiEvidenceRef {
  ref: string;
  kind: 'FRAME' | 'TRANSCRIPT' | string;
  source_epoch: string;
  sequence: number;
  evidence_id: string | null;
  media_start_ms: number;
  media_end_ms: number;
  received_at_utc: string;
  frame_url?: string | null;
  transcript_text?: string | null;
  untrusted?: boolean;
}

export interface AiCandidate {
  id: string;
  candidate_id: string;
  stream_session_id: string;
  source_epoch: string;
  status: 'PENDING' | 'SHADOW' | 'OPENED' | 'REJECTED' | 'EXPIRED' | string;
  reject_code: string | null;
  actionable: boolean;
  market_id: string | null;
  template_id: string;
  episode_fingerprint: string;
  question: string;
  yes: { label: string; predicate: string };
  no: { label: string; predicate: string };
  subjects: string[];
  evidence_ids: string[];
  evidence: AiEvidenceRef[];
  announced_at_media_ms: number;
  suggested_close_in_s: number;
  suggested_resolve_in_s: number;
  close_in_s: number | null;
  resolve_in_s: number | null;
  proposed_close_at_utc: string | null;
  cancellation_conditions: string[];
  rationale: string;
  rationale_untrusted: boolean;
  model: string;
  prompt_version: string;
  ai_mode: string;
  received_at_utc: string;
  expires_at_utc: string;
  decided_at_utc: string | null;
  decided_by_user_id: string | null;
  decision_note: string | null;
}

export interface CandidateList {
  schema_version: 1;
  server_time_utc: string;
  stream_session_id: string | null;
  ai_mode: string | null;
  effective_ai_mode: string | null;
  allow_automatic: boolean;
  candidate_expiry_s: number;
  candidates: AiCandidate[];
}

export interface AiResolution {
  id: string;
  resolution_id: string;
  market_id: string;
  market_state: string | null;
  market_resolve_by_utc: string | null;
  rules_version: number;
  source_epoch: string;
  decision: 'YES' | 'NO' | 'WAIT' | 'UNRESOLVABLE' | string;
  status: 'RECORDED' | 'SETTLED' | 'VOIDED' | 'PENDING_APPROVAL' | 'IGNORED' | string;
  status_reason: string | null;
  actionable: boolean;
  evidence_ids: string[];
  evidence: AiEvidenceRef[];
  media_interval: { start_ms: number; end_ms: number };
  predicate_support: { YES: boolean; NO: boolean };
  contradictions: string[];
  reason: string;
  reason_untrusted: boolean;
  model: string;
  prompt_version: string;
  ai_mode: string;
  received_at_utc: string;
  decided_at_utc: string | null;
  decided_by_user_id: string | null;
}

export interface ResolutionList {
  schema_version: 1;
  server_time_utc: string;
  market_id: string | null;
  resolutions: AiResolution[];
}

export interface CandidateApproveReceipt extends OperatorReceipt {
  candidate: AiCandidate;
  market: OperatorMarket;
}

export interface CandidateRejectReceipt extends OperatorReceipt {
  candidate: AiCandidate;
}

export interface AiModeReceipt extends OperatorReceipt {
  stream_session_id: string;
  ai_mode: string;
  previous_ai_mode: string;
  allow_automatic: boolean;
}

export interface ResolutionApproveReceipt extends OperatorReceipt {
  resolution: AiResolution;
  market: OperatorMarket;
}
