import { describe, expect, it } from 'vitest';
import { BackgroundClient } from '../src/api/client';
import { PORT_NAME, type PortLike } from '../src/api/protocol';
import { attachRouter, type RuntimeLike } from '../src/api/router';
import { MockBackend } from '../src/mock/backend';

type Listener<T extends unknown[]> = (...args: T) => void;
function event<T extends unknown[]>() {
  const ls = new Set<Listener<T>>();
  return { addListener: (l: Listener<T>) => ls.add(l), removeListener: (l: Listener<T>) => ls.delete(l), fire: (...a: T) => [...ls].forEach((l) => l(...a)) };
}

/** In-memory runtime Port pair with structured-clone delivery, like chrome.runtime ports. */
function portPair(senderId: string) {
  const mk = () => ({ onMessage: event<[unknown]>(), onDisconnect: event<[]>() });
  const a = mk();
  const b = mk();
  let open = true;
  const end = (self: ReturnType<typeof mk>, other: ReturnType<typeof mk>, sender?: { id: string }): PortLike & { sender?: { id: string } } => ({
    name: PORT_NAME,
    sender,
    postMessage: (m) => {
      if (!open) throw new Error('disconnected');
      const copy = structuredClone(m);
      queueMicrotask(() => open && other.onMessage.fire(copy));
    },
    disconnect: () => {
      if (!open) return;
      open = false;
      other.onDisconnect.fire(); // Only the other end is notified.
    },
    onMessage: self.onMessage,
    onDisconnect: self.onDisconnect,
  });
  return { client: end(a, b), server: end(b, a, { id: senderId }) };
}

function setup(senderId = 'ext-id') {
  const onConnect = event<[PortLike & { sender?: { id?: string } }]>();
  const runtime: RuntimeLike = { id: 'ext-id', onConnect };
  const backend = new MockBackend();
  const detach = attachRouter(backend, runtime);
  const pushes: unknown[] = [];
  let serverEnd: PortLike | null = null;
  const client = new BackgroundClient({
    connect: () => {
      const { client: c, server } = portPair(senderId);
      serverEnd = server;
      onConnect.fire(server);
      return c;
    },
    onPush: (m) => pushes.push(m),
    timeoutMs: 500,
  });
  return { client, backend, pushes, detach, killServer: () => serverEnd?.disconnect() };
}

describe('content <-> background port protocol', () => {
  it('round-trips requests and pushes hello + snapshots after mutations', async () => {
    const { client, pushes, backend } = setup();
    const snap = await client.getSnapshot();
    expect(snap.ok).toBe(true);
    expect(pushes[0]).toMatchObject({ t: 'hello', mode: 'MOCK', fixtures: true });
    await backend.fixtures.load('no_market');
    await new Promise((r) => setTimeout(r, 10));
    expect(pushes.some((p) => (p as { t: string }).t === 'snapshot')).toBe(true);
    const fx = await client.fixtures.info();
    expect(fx).toMatchObject({ ok: true, body: { current: 'no_market' } });
    client.dispose();
  });

  it('rejects ports from a foreign sender', async () => {
    const { client } = setup('someone-else');
    const r = await client.getSnapshot();
    expect(r).toMatchObject({ ok: false, kind: 'unknown' });
    client.dispose();
  });

  it('a lost background connection makes in-flight requests UNKNOWN (never success)', async () => {
    const { client, killServer } = setup();
    await client.getSnapshot();
    const pending = client.getSnapshot();
    killServer();
    expect(await pending).toMatchObject({ ok: false, kind: 'unknown' });
    client.dispose();
  });

  it('validates request params in the background', async () => {
    const { client } = setup();
    expect(await client.request('getOperation', { nope: 1 })).toMatchObject({ ok: false, kind: 'http', error: { error: { code: 'VALIDATION_FAILED' } } });
    expect(await client.request('fixtures.injectError', { code: 'NOT_A_CODE' })).toMatchObject({ ok: false, error: { error: { code: 'VALIDATION_FAILED' } } });
    client.dispose();
  });
});
