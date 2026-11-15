// Adapter boundary. The background service worker owns a BackendAdapter (P1: MockBackend;
// P2: live HTTP/WS adapter). Content scripts never call the API: they use BackgroundClient, which
// implements the same async interfaces over a runtime Port (see protocol.ts). Components depend
// only on MarketDataSource / WalletApi, so P2 swaps the background adapter without touching UI.

import type {
  ErrorCode,
  ErrorEnvelope,
  Me,
  PageVisibility,
  PaymentMode,
  PlayerState,
  PresenceAck,
  StreamSnapshot,
  WagerReceiptResponse,
  WagerRequest,
  WalletSummary,
} from '@fazetime/contracts';

/**
 * - ok: a definitive 2xx answer.
 * - http: a definitive typed error (CONTRACTS 9.10) unless `error.error.retryable`.
 * - unknown: transport failure, timeout or lost connection. The outcome is UNKNOWN: retry the same
 *   operation_id or look it up; never show success (CONTRACTS 9.7, 9.10).
 */
export type ApiResult<T> =
  | { ok: true; status: number; body: T }
  | { ok: false; kind: 'http'; status: number; error: ErrorEnvelope }
  | { ok: false; kind: 'unknown'; message: string };

// --- CONTRACTS 9.20 item 2 (additive, optional): the expected result time on the public market view. ---

/**
 * `expected_result_at_utc` = close_at_utc + the worker's expected_result_in_s; null when unknown, and for H2H and
 * fixture markets; absent on older servers. Display only: it never settles or authorizes anything. Kept here, not
 * in @fazetime/contracts, because the validator already passes unknown keys through.
 */
export interface MarketResultEta {
  expected_result_at_utc?: string | null;
}

// --- P1-local MOCK shapes (NOT contract v1). Redemption stays a P1 mock. ---

export interface TopUpRequest {
  operation_id: string;
  amount_minor: number;
}

export interface TopUpReceipt {
  schema_version: 1;
  topup_id: string;
  operation_id: string;
  amount_minor: number;
  /** P1 credits synthetic demo funds immediately. No payment provider is involved. */
  status: 'MOCK_CREDITED';
  payment_mode: 'MOCK';
  wallet_after: WalletSummary;
  replayed: boolean;
}

// --- P6 Stripe test top-ups (CONTRACTS 9.18) ---

export const TOPUP_STATUSES = ['CREATED', 'PENDING', 'CREDITED', 'FAILED', 'EXPIRED'] as const;
export type TopupStatus = (typeof TOPUP_STATUSES)[number];
export const TOPUP_ID_PATTERN = /^top_[0-9a-f]{32}$/;

/**
 * Server `TopupReceipt` (CONTRACTS 9.18). BACKGROUND ONLY: `checkout_url` is opened with
 * chrome.tabs.create by the background and is never logged, stored or posted to a tab.
 */
export interface StripeTopupReceipt {
  schema_version: 1;
  topup_id: string;
  operation_id: string;
  /** The run this top-up credits, even after a reset (9.5, 9.18). */
  stream_session_id: string;
  amount_minor: number;
  currency: 'usd';
  status: TopupStatus;
  payment_mode: PaymentMode;
  checkout_url: string | null;
  checkout_expires_at_utc: string | null;
  replayed: boolean;
}

/**
 * What tabs see of the one tracked Stripe test top-up. Never contains the Checkout URL or a token.
 * `status` comes only from the server (GET /v1/topups/{id}); a return URL never sets it.
 */
export interface TopUpTracking {
  payment_mode: 'STRIPE_TEST';
  topup_id: string | null;
  operation_id: string;
  amount_minor: number;
  /** SUBMITTING: the create request is in flight or its outcome is unknown (retry with the same key). */
  status: TopupStatus | 'SUBMITTING';
  /** The background opened Stripe Checkout in a new tab for this top-up. */
  checkout_opened: boolean;
  /** The background refused to open the link (not a https://checkout.stripe.com page) or the tab failed. */
  checkout_blocked: boolean;
  /** The top-up belongs to a different (earlier) demo run than the one on screen. */
  previous_run: boolean;
  /** The background is still polling the server for this top-up. */
  watching: boolean;
  updated_at_ms: number;
}

export function isTopUpTracking(v: unknown): v is TopUpTracking {
  if (typeof v !== 'object' || v === null) return false;
  const t = v as Record<string, unknown>;
  return (
    t.payment_mode === 'STRIPE_TEST' &&
    (t.topup_id === null || (typeof t.topup_id === 'string' && TOPUP_ID_PATTERN.test(t.topup_id))) &&
    typeof t.operation_id === 'string' &&
    Number.isSafeInteger(t.amount_minor) &&
    (t.status === 'SUBMITTING' || (TOPUP_STATUSES as readonly string[]).includes(String(t.status))) &&
    typeof t.checkout_opened === 'boolean' &&
    typeof t.checkout_blocked === 'boolean' &&
    typeof t.previous_run === 'boolean' &&
    typeof t.watching === 'boolean'
  );
}

export interface RedeemItem {
  item_id: string;
  title: string;
  description: string;
  price_minor: number;
}

export interface RedeemCatalog {
  schema_version: 1;
  label: 'DEMO_ONLY_NOT_REDEEMABLE';
  items: RedeemItem[];
}

export interface RedemptionRequest {
  operation_id: string;
  item_id: string;
}

export interface RedemptionReceipt {
  schema_version: 1;
  redemption_id: string;
  operation_id: string;
  item_id: string;
  price_minor: number;
  /** Random demo code. NON-REDEEMABLE: no retailer, coupon or fulfillment exists. */
  demo_code: string;
  non_redeemable: true;
  wallet_after: WalletSummary;
  replayed: boolean;
}

// --- Interfaces used by the UI ---

export interface MarketDataSource {
  /** GET /v1/streams/{stream_id}/snapshot */
  getSnapshot(): Promise<ApiResult<StreamSnapshot>>;
}

export interface WalletApi {
  /** POST /v1/wagers */
  placeWager(req: WagerRequest): Promise<ApiResult<WagerReceiptResponse>>;
  /** GET /v1/operations/{operation_id} */
  getOperation(operationId: string): Promise<ApiResult<WagerReceiptResponse>>;
  /**
   * MOCK: immediate synthetic credit (TopUpReceipt). LIVE (P6): POST /v1/topups; the background opens
   * Stripe-hosted Checkout in a new tab and returns the tracking view (no URL). Credit arrives later.
   */
  createTopUp(req: TopUpRequest): Promise<ApiResult<TopUpReceipt | TopUpTracking>>;
  /** P1-only fixed demo catalog. */
  getCatalog(): Promise<ApiResult<RedeemCatalog>>;
  /** POST /v1/redemptions (P1 mock). */
  redeem(req: RedemptionRequest): Promise<ApiResult<RedemptionReceipt>>;
}

export interface FixtureInfo {
  names: string[];
  current: string;
  injectedError: ErrorCode | null;
  timeoutArmed: boolean;
  errorCodes: ErrorCode[];
}

/** Dev-only controls; only the mock adapter provides them. */
export interface FixtureControls {
  info(): Promise<FixtureInfo>;
  load(name: string): Promise<FixtureInfo>;
  injectError(code: ErrorCode | null): Promise<FixtureInfo>;
  armTimeout(): Promise<FixtureInfo>;
}

export type LinkState = 'MOCK' | 'IDLE' | 'NEEDS_ENROLL' | 'NO_STREAM' | 'CONNECTING' | 'LIVE' | 'POLLING' | 'ORIGIN_REJECTED';

/** Non-secret background status pushed to tabs and the popup. Never contains the session token. */
export interface BackgroundStatus {
  mode: 'MOCK' | 'LIVE';
  link: LinkState;
  enrolled: boolean;
  reenroll: boolean;
  displayName: string | null;
  role: string | null;
  apiBase: string | null;
  channel: string | null;
  message: string | null;
}

export interface PresenceInput {
  tab_instance_id: string;
  observed_channel_login: string | null;
  page_visibility: PageVisibility;
  player_state: PlayerState;
}

export interface EnrollInput {
  /**
   * Omitted, null or blank: name-only enroll (D35 open access). An invite-only server answers 401
   * UNAUTHENTICATED, and the popup then asks for an invite code and retries with it.
   */
  invite_code?: string | null;
  display_name: string;
  claimed_twitch_login: string | null;
}

/** What the background owns. */
export interface BackendAdapter extends MarketDataSource, WalletApi {
  readonly mode: 'MOCK' | 'LIVE';
  readonly fixtures?: FixtureControls;
  /** Called when authoritative state may have changed (mock mutation; live: WS event or poll). */
  onChange(listener: () => void): () => void;
  status?(): BackgroundStatus;
  onStatus?(listener: () => void): () => void;
  /** Latest state for pushes without a network round trip (live adapter). */
  peekSnapshot?(): ApiResult<StreamSnapshot> | null;
  /** Number of connected tabs; the live socket runs only while someone watches. */
  setDemand?(tabs: number): void;
  /** A tab connected (new page or reload): refresh the snapshot once in the background. */
  onTabConnected?(): void;
  presence?(input: PresenceInput): Promise<ApiResult<PresenceAck>>;
  /** P6 (live): the one tracked Stripe test top-up, for pushes to tabs. */
  peekTopUp?(): TopUpTracking | null;
  onTopUp?(listener: () => void): () => void;
  /** The page URL carried ?fazetime_topup=<id>: poll now. A hint only; it never credits. */
  topUpHint?(topupId: string): Promise<ApiResult<TopUpTracking | null>>;
  /** User-initiated: reopen Checkout (or re-send an unconfirmed create) with the SAME operation_id. */
  reopenTopUpCheckout?(): Promise<ApiResult<TopUpTracking | null>>;
  /** Forget a finished top-up result after the user acknowledged it. */
  dismissTopUp?(): Promise<ApiResult<null>>;
  enroll?(input: EnrollInput): Promise<ApiResult<{ me: Me }>>;
  signOut?(): Promise<void>;
}

export const MOCK_STATUS: BackgroundStatus = {
  mode: 'MOCK',
  link: 'MOCK',
  enrolled: false,
  reenroll: false,
  displayName: null,
  role: null,
  apiBase: null,
  channel: null,
  message: null,
};
