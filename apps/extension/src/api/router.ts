// Background side of the port protocol. Owns the adapter; content scripts only send requests.

import { isErrorCode, isRequestMessage, PORT_NAME, POPUP_METHODS, type PopupRequest, type PortLike, type PushMessage, type RequestMessage } from './protocol';
import { httpError } from './errors';
import { MOCK_STATUS, TOPUP_ID_PATTERN, type ApiResult, type BackendAdapter, type PresenceInput, type RedemptionRequest, type TopUpRequest } from './types';
import type { WagerRequest } from '@fazetime/contracts';

const isPlainObject = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v) && Object.getPrototypeOf(v) === Object.prototype;

export async function handleRequest(adapter: BackendAdapter, msg: RequestMessage): Promise<ApiResult<unknown>> {
  const params = msg.params;
  switch (msg.method) {
    case 'getSnapshot':
      return adapter.getSnapshot();
    case 'placeWager':
      if (!isPlainObject(params)) return httpError('VALIDATION_FAILED', 'Wager body must be an object.');
      return adapter.placeWager(params as unknown as WagerRequest);
    case 'getOperation':
      if (!isPlainObject(params) || typeof params.operation_id !== 'string') return httpError('VALIDATION_FAILED', 'operation_id required.');
      return adapter.getOperation(params.operation_id);
    case 'createTopUp':
      if (!isPlainObject(params)) return httpError('VALIDATION_FAILED', 'Top-up body must be an object.');
      return adapter.createTopUp(params as unknown as TopUpRequest);
    case 'topupHint':
      if (!adapter.topUpHint) return httpError('CAPABILITY_UNAVAILABLE', 'Stripe test top-ups exist only in live builds.');
      if (!isPlainObject(params) || typeof params.topup_id !== 'string' || !TOPUP_ID_PATTERN.test(params.topup_id))
        return httpError('VALIDATION_FAILED', 'Bad topup_id.');
      return adapter.topUpHint(params.topup_id);
    case 'reopenTopUpCheckout':
      if (!adapter.reopenTopUpCheckout) return httpError('CAPABILITY_UNAVAILABLE', 'Stripe test top-ups exist only in live builds.');
      return adapter.reopenTopUpCheckout();
    case 'dismissTopUp':
      if (!adapter.dismissTopUp) return httpError('CAPABILITY_UNAVAILABLE', 'Stripe test top-ups exist only in live builds.');
      return adapter.dismissTopUp();
    case 'getCatalog':
      return adapter.getCatalog();
    case 'status':
      return { ok: true, status: 200, body: adapter.status?.() ?? MOCK_STATUS };
    case 'presence': {
      if (!adapter.presence) return httpError('CAPABILITY_UNAVAILABLE', 'Presence is reported only in live builds.');
      if (!isPlainObject(params)) return httpError('VALIDATION_FAILED', 'Presence body must be an object.');
      const p = params as Record<string, unknown>;
      const vis = ['VISIBLE', 'HIDDEN', 'UNKNOWN'];
      const player = ['PLAYING', 'PAUSED', 'BUFFERING', 'UNKNOWN'];
      if (typeof p.tab_instance_id !== 'string' || !vis.includes(String(p.page_visibility)) || !player.includes(String(p.player_state)))
        return httpError('VALIDATION_FAILED', 'Bad presence body.');
      const login = typeof p.observed_channel_login === 'string' && /^[a-z0-9_]{1,25}$/.test(p.observed_channel_login) ? p.observed_channel_login : null;
      return adapter.presence({
        tab_instance_id: p.tab_instance_id,
        observed_channel_login: login,
        page_visibility: p.page_visibility as PresenceInput['page_visibility'],
        player_state: p.player_state as PresenceInput['player_state'],
      });
    }
    case 'redeem':
      if (!isPlainObject(params)) return httpError('VALIDATION_FAILED', 'Redemption body must be an object.');
      return adapter.redeem(params as unknown as RedemptionRequest);
    case 'fixtures.info':
    case 'fixtures.load':
    case 'fixtures.injectError':
    case 'fixtures.armTimeout': {
      const fx = adapter.fixtures;
      if (!fx) return httpError('CAPABILITY_UNAVAILABLE', 'Fixture controls exist only in the MOCK build.');
      if (msg.method === 'fixtures.info') return { ok: true, status: 200, body: await fx.info() };
      if (msg.method === 'fixtures.armTimeout') return { ok: true, status: 200, body: await fx.armTimeout() };
      if (msg.method === 'fixtures.load') {
        if (!isPlainObject(params) || typeof params.name !== 'string') return httpError('VALIDATION_FAILED', 'Fixture name required.');
        return { ok: true, status: 200, body: await fx.load(params.name) };
      }
      const code = isPlainObject(params) ? params.code : undefined;
      if (code !== null && !isErrorCode(code)) return httpError('VALIDATION_FAILED', 'Unknown error code.');
      return { ok: true, status: 200, body: await fx.injectError(code) };
    }
  }
}

export interface RuntimeLike {
  id?: string;
  onConnect: {
    addListener(cb: (port: PortLike & { sender?: { id?: string } }) => void): void;
    removeListener(cb: (port: PortLike & { sender?: { id?: string } }) => void): void;
  };
}

function safePost(port: PortLike, msg: unknown): void {
  try {
    port.postMessage(msg);
  } catch {
    // The port closed between the check and the post; the tab will resync on reconnect.
  }
}

export function attachRouter(adapter: BackendAdapter, runtime: RuntimeLike): () => void {
  const ports = new Set<PortLike>();

  const onConnect = (port: PortLike & { sender?: { id?: string } }) => {
    if (port.name !== PORT_NAME) return;
    // Only this extension's own contexts may connect (no externally_connectable is declared).
    if (!runtime.id || port.sender?.id !== runtime.id) {
      port.disconnect();
      return;
    }
    ports.add(port);
    adapter.setDemand?.(ports.size);
    port.onMessage.addListener(async (msg: unknown) => {
      if (!isRequestMessage(msg)) return;
      let result: ApiResult<unknown>;
      try {
        result = await handleRequest(adapter, msg);
      } catch (err) {
        console.error('[FaZeTime] background request failed', err);
        result = httpError('INTERNAL_ERROR', 'The extension background failed; the outcome is unknown.');
      }
      safePost(port, { t: 'res', id: msg.id, result });
    });
    port.onDisconnect.addListener(() => {
      ports.delete(port);
      adapter.setDemand?.(ports.size);
    });
    const hello: PushMessage = { t: 'hello', mode: adapter.mode, fixtures: Boolean(adapter.fixtures) };
    safePost(port, hello);
    safePost(port, { t: 'status', status: adapter.status?.() ?? MOCK_STATUS } satisfies PushMessage);
    // A new tab (or reload): serve the cache immediately, then refresh once from the server.
    const cached = adapter.peekSnapshot?.();
    if (cached) safePost(port, { t: 'snapshot', result: cached } satisfies PushMessage);
    if (adapter.peekTopUp) safePost(port, { t: 'topup', topup: adapter.peekTopUp() } satisfies PushMessage);
    adapter.onTabConnected?.();
  };

  runtime.onConnect.addListener(onConnect);
  const unsubscribe = adapter.onChange(async () => {
    if (ports.size === 0) return;
    const result = adapter.peekSnapshot?.() ?? (await adapter.getSnapshot());
    for (const port of ports) safePost(port, { t: 'snapshot', result } satisfies PushMessage);
  });
  const unsubscribeStatus = adapter.onStatus?.(() => {
    const status = adapter.status?.() ?? MOCK_STATUS;
    for (const port of ports) safePost(port, { t: 'status', status } satisfies PushMessage);
  });
  const unsubscribeTopUp = adapter.onTopUp?.(() => {
    const topup = adapter.peekTopUp?.() ?? null;
    for (const port of ports) safePost(port, { t: 'topup', topup } satisfies PushMessage);
  });

  return () => {
    runtime.onConnect.removeListener(onConnect);
    unsubscribe();
    unsubscribeStatus?.();
    unsubscribeTopUp?.();
    for (const port of ports) port.disconnect();
    ports.clear();
  };
}

export interface MessageRuntimeLike {
  id?: string;
  onMessage: {
    addListener(cb: (msg: unknown, sender: { id?: string; tab?: unknown; url?: string }, sendResponse: (r: unknown) => void) => boolean | void): void;
  };
}

/** Popup -> background requests (enrollment). Only extension pages, never content scripts or the page. */
export function attachPopupHandler(adapter: BackendAdapter, runtime: MessageRuntimeLike): void {
  runtime.onMessage.addListener((msg, sender, sendResponse) => {
    const m = msg as Partial<PopupRequest> | null;
    if (!m || m.t !== 'popup' || !POPUP_METHODS.includes(m.method as never)) return;
    // sender.url is set by the browser: a content script reports the web page URL, so it is refused here.
    const fromExtensionPage = sender.id === runtime.id && typeof sender.url === 'string' && sender.url.startsWith(`chrome-extension://${runtime.id}/`);
    if (!fromExtensionPage) {
      sendResponse(httpError('FORBIDDEN', 'Only the extension popup may call this.'));
      return;
    }
    void (async (): Promise<ApiResult<unknown>> => {
      if (m.method === 'status') return { ok: true, status: 200, body: adapter.status?.() ?? MOCK_STATUS };
      if (m.method === 'signout') {
        await adapter.signOut?.();
        return { ok: true, status: 200, body: adapter.status?.() ?? MOCK_STATUS };
      }
      if (!adapter.enroll) return httpError('CAPABILITY_UNAVAILABLE', 'Enrollment exists only in live builds.');
      const p = isPlainObject(m.params) ? m.params : {};
      if (typeof p.invite_code !== 'string' || typeof p.display_name !== 'string')
        return httpError('VALIDATION_FAILED', 'Invite code and display name are required.');
      const login = typeof p.claimed_twitch_login === 'string' && p.claimed_twitch_login.trim() !== '' ? p.claimed_twitch_login : null;
      return adapter.enroll({ invite_code: p.invite_code, display_name: p.display_name, claimed_twitch_login: login });
    })()
      .catch(() => httpError('INTERNAL_ERROR', 'The background failed.'))
      .then(sendResponse);
    return true; // Async response.
  });
}
