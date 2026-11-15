// Background side of the port protocol. Owns the adapter; content scripts only send requests.

import { isErrorCode, isRequestMessage, PORT_NAME, type PortLike, type PushMessage, type RequestMessage } from './protocol';
import { httpError } from './errors';
import type { ApiResult, BackendAdapter, RedemptionRequest, TopUpRequest } from './types';
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
    case 'getCatalog':
      return adapter.getCatalog();
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
    port.onDisconnect.addListener(() => ports.delete(port));
    const hello: PushMessage = { t: 'hello', mode: adapter.mode, fixtures: Boolean(adapter.fixtures) };
    safePost(port, hello);
  };

  runtime.onConnect.addListener(onConnect);
  const unsubscribe = adapter.onChange(async () => {
    if (ports.size === 0) return;
    const result = await adapter.getSnapshot();
    for (const port of ports) safePost(port, { t: 'snapshot', result } satisfies PushMessage);
  });

  return () => {
    runtime.onConnect.removeListener(onConnect);
    unsubscribe();
    for (const port of ports) port.disconnect();
    ports.clear();
  };
}
