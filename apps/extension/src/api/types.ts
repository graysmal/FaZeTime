// Adapter boundary. The background service worker owns a BackendAdapter (P1: MockBackend;
// P2: live HTTP/WS adapter). Content scripts never call the API: they use BackgroundClient, which
// implements the same async interfaces over a runtime Port (see protocol.ts). Components depend
// only on MarketDataSource / WalletApi, so P2 swaps the background adapter without touching UI.

import type { ErrorCode, ErrorEnvelope, StreamSnapshot, WagerReceiptResponse, WagerRequest, WalletSummary } from '@fazetime/contracts';

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

// --- P1-local shapes (NOT contract v1). P6 defines real top-ups; redemption is a P1 mock. ---

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
  /** P1 mock credit. P6: POST /v1/topups returns a Stripe-hosted Checkout URL instead. */
  createTopUp(req: TopUpRequest): Promise<ApiResult<TopUpReceipt>>;
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

/** What the background owns. */
export interface BackendAdapter extends MarketDataSource, WalletApi {
  readonly mode: 'MOCK' | 'LIVE';
  readonly fixtures?: FixtureControls;
  /** Called when authoritative state may have changed (mock mutation; P2: WS event or poll). */
  onChange(listener: () => void): () => void;
}
