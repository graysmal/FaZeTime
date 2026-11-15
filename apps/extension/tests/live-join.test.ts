// D35 open access: name-only join, silent re-join after a 401 or an expired session, and the invite-only fallback.
import { describe, expect, it } from 'vitest';
import type { StreamSnapshot } from '@fazetime/contracts';
import { attachPopupHandler, type MessageRuntimeLike } from '../src/api/router';
import type { ApiResult, BackendAdapter, EnrollInput } from '../src/api/types';
import { defaultDisplayName, refusesNameOnly } from '../src/lib/join';
import { LiveBackend, type JoinProfile, type LiveStore, type SessionRecord } from '../src/live/backend';
import { loadSnapshotFixture } from '../src/mock/fixtures';

const tok = (n: number) => `fzs_${String(n).padStart(43, 'T')}`;
const USER = `usr_${'b'.repeat(32)}`;
const SES = `ses_${'a'.repeat(32)}`;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const future = () => new Date(Date.now() + 3.6e6).toISOString();
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const envelope = (code: string, details: unknown = null) => ({
  schema_version: 1,
  error: { code, message: 'x', retryable: false, retry_after_ms: null, request_id: `req_${'c'.repeat(32)}`, operation_id: null, details },
  server_time_utc: new Date().toISOString(),
});

interface Call {
  path: string;
  token: string | null;
}

/** A fake API: tokens are valid until revoked; open access accepts name-only enroll (D35). */
function fakeApi(opts: { openAccess?: boolean; rejectEveryToken?: boolean } = {}) {
  const snap: StreamSnapshot = loadSnapshotFixture('open_no_position', Date.now());
  const valid = new Set<string>([tok(1)]);
  const enrollBodies: Record<string, unknown>[] = [];
  const calls: Call[] = [];
  let issued = 1;
  const me = (name: string, login: string | null = null) => ({
    server_time_utc: snap.server_time_utc,
    user: { user_id: USER, display_name: name, claimed_twitch_login: login, role: 'VIEWER' },
    session: { session_id: SES, expires_at_utc: future() },
    current_stream: { stream_id: snap.stream.stream_id, twitch_channel_login: 'fazegavin1234', stream_session_id: snap.stream.stream_session_id },
    wallet: snap.wallet,
  });
  const fetchImpl = (async (url: string, init?: RequestInit) => {
    const path = new URL(url).pathname;
    const auth = (init?.headers as Record<string, string>)?.Authorization ?? null;
    const token = auth ? auth.replace(/^Bearer /, '') : null;
    calls.push({ path, token });
    if (path === '/v1/enroll') {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      enrollBodies.push(body);
      const open = opts.openAccess ?? true;
      if (!open && typeof body.invite_code !== 'string') return json(401, envelope('UNAUTHENTICATED'));
      issued += 1;
      if (!opts.rejectEveryToken) valid.add(tok(issued));
      return json(201, { schema_version: 1, session_token: tok(issued), session_id: SES, expires_at_utc: future(), me: me(String(body.display_name), (body.claimed_twitch_login as string | null) ?? null) });
    }
    if (!token || !valid.has(token)) return json(401, envelope('UNAUTHENTICATED'));
    if (path === '/v1/me') return json(200, { schema_version: 1, ...me('Alice') });
    if (path.endsWith('/snapshot')) return json(200, { ...snap, server_time_utc: new Date().toISOString() });
    if (path.startsWith('/v1/operations/')) return json(404, envelope('NOT_FOUND'));
    return json(404, envelope('NOT_FOUND'));
  }) as unknown as typeof fetch;
  return { fetchImpl, valid, enrollBodies, calls, revoke: (t: string) => void valid.delete(t) };
}

function makeBackend(api: ReturnType<typeof fakeApi>, opts: { session?: SessionRecord | null; profile?: JoinProfile | null } = {}) {
  const store: LiveStore & { session: SessionRecord | null; profile: JoinProfile | null } = {
    session:
      opts.session === undefined
        ? { token: tok(1), session_id: SES, expires_at_utc: future(), user_id: USER, display_name: 'Alice', role: 'VIEWER' }
        : opts.session,
    profile: opts.profile ?? null,
    getSession: async () => store.session,
    setSession: async (s) => void (store.session = s),
    getDeviceId: async () => '00000000-0000-4000-8000-00000000d001',
    getJoinProfile: async () => store.profile,
    setJoinProfile: async (p) => void (store.profile = p),
  };
  const backend = new LiveBackend({ apiBase: 'http://127.0.0.1:8000', channel: 'fazegavin1234', extensionVersion: 'test', store, fetch: api.fetchImpl });
  return { backend, store };
}

describe('D35 name-only join', () => {
  it('omits invite_code entirely, and an empty name gets a "Viewer 1234" default', async () => {
    const api = fakeApi();
    const { backend, store } = makeBackend(api, { session: null });
    const r = await backend.enroll({ display_name: '  ', claimed_twitch_login: null });
    expect(r.ok).toBe(true);
    expect(api.enrollBodies).toHaveLength(1);
    expect('invite_code' in api.enrollBodies[0]!).toBe(false);
    expect(api.enrollBodies[0]!.display_name).toMatch(/^Viewer \d{4}$/);
    expect(api.enrollBodies[0]!.device_id).toBe('00000000-0000-4000-8000-00000000d001');
    expect(store.profile?.display_name).toMatch(/^Viewer \d{4}$/); // Stored for silent re-join.
    expect(JSON.stringify(r)).not.toContain('fzs_'); // The token never leaves the background.
  });

  it('sends the trimmed invite code only when the popup provides one', async () => {
    const api = fakeApi({ openAccess: false });
    const { backend } = makeBackend(api, { session: null });
    const first = await backend.enroll({ display_name: 'Alice', claimed_twitch_login: null });
    expect(first).toMatchObject({ ok: false, status: 401 });
    expect(refusesNameOnly(first)).toBe(true);
    const second = await backend.enroll({ invite_code: ' ABCD-EFGH-JKMN ', display_name: 'Alice', claimed_twitch_login: null });
    expect(second.ok).toBe(true);
    expect(api.enrollBodies[1]!.invite_code).toBe('ABCD-EFGH-JKMN');
  });

  it('defaultDisplayName is "Viewer" plus 4 digits', () => {
    for (let i = 0; i < 20; i++) expect(defaultDisplayName()).toMatch(/^Viewer \d{4}$/);
  });

  it('refusesNameOnly: 401, or an older API whose validation names invite_code; nothing else', () => {
    const http = (status: number, code: string, details: unknown = null): ApiResult<unknown> => ({ ok: false, kind: 'http', status, error: envelope(code, details) as never });
    expect(refusesNameOnly(http(401, 'UNAUTHENTICATED'))).toBe(true);
    expect(refusesNameOnly(http(400, 'VALIDATION_FAILED', { fields: [{ loc: ['body', 'invite_code'], msg: 'Field required' }] }))).toBe(true);
    expect(refusesNameOnly(http(400, 'VALIDATION_FAILED', { fields: [{ loc: ['body', 'display_name'], msg: 'too long' }] }))).toBe(false);
    expect(refusesNameOnly(http(429, 'RATE_LIMITED'))).toBe(false);
    expect(refusesNameOnly({ ok: false, kind: 'unknown', message: 'offline' })).toBe(false);
  });
});

describe('D35 silent re-join', () => {
  it('a 401 re-joins name-only with the stored name, then retries the request once', async () => {
    const api = fakeApi();
    const { backend, store } = makeBackend(api, { profile: { display_name: 'Alice', claimed_twitch_login: 'alice_tv' } });
    api.revoke(tok(1)); // e.g. the server was reset or the session expired server-side.
    const r = await backend.getSnapshot();
    expect(r.ok).toBe(true);
    expect(api.enrollBodies).toHaveLength(1);
    expect(api.enrollBodies[0]).toEqual({ display_name: 'Alice', claimed_twitch_login: 'alice_tv', device_id: '00000000-0000-4000-8000-00000000d001' });
    expect(api.calls.map((c) => [c.path.replace(/str_[0-9a-f]+/, 'str_x'), c.token])).toEqual([
      ['/v1/me', tok(1)],
      ['/v1/enroll', null],
      ['/v1/me', tok(2)],
      ['/v1/streams/str_x/snapshot', tok(2)],
    ]);
    expect(store.session?.token).toBe(tok(2));
    expect(backend.rejoins).toBe(1);
    expect(backend.status()).toMatchObject({ enrolled: true, reenroll: false, displayName: 'Alice' });
    expect(JSON.stringify(backend.status())).not.toContain('fzs_');
  });

  it('concurrent 401s share ONE re-join and each request is retried once', async () => {
    const api = fakeApi();
    const { backend } = makeBackend(api);
    api.revoke(tok(1));
    const op = (n: number) => `00000000-0000-4000-8000-00000000000${n}`;
    const results = await Promise.all([backend.getOperation(op(1)), backend.getOperation(op(2)), backend.getOperation(op(3))]);
    for (const r of results) expect(r).toMatchObject({ ok: false, status: 404 }); // Reached the server with the new token.
    expect(api.enrollBodies).toHaveLength(1);
    const ops = api.calls.filter((c) => c.path.startsWith('/v1/operations/'));
    expect(ops.filter((c) => c.token === tok(1))).toHaveLength(3);
    expect(ops.filter((c) => c.token === tok(2))).toHaveLength(3);
  });

  it('an expired stored session re-joins silently at startup, with no popup', async () => {
    const api = fakeApi();
    const expired: SessionRecord = { token: tok(1), session_id: SES, expires_at_utc: new Date(Date.now() - 1000).toISOString(), user_id: USER, display_name: 'Alice', role: 'VIEWER' };
    const { backend, store } = makeBackend(api, { session: expired }); // No stored profile: the session's name is reused.
    await sleep(50);
    expect(api.enrollBodies).toHaveLength(1);
    expect(api.enrollBodies[0]!.display_name).toBe('Alice');
    expect('invite_code' in api.enrollBodies[0]!).toBe(false);
    expect(store.session?.token).toBe(tok(2));
    expect(backend.status()).toMatchObject({ enrolled: true, reenroll: false });
  });

  it('an invite-only server refuses the silent re-join: the session is cleared and nothing retries in a loop', async () => {
    const api = fakeApi({ openAccess: false });
    const { backend, store } = makeBackend(api);
    api.revoke(tok(1));
    const r = await backend.getSnapshot();
    expect(r).toMatchObject({ ok: false, status: 401 });
    expect(api.enrollBodies).toHaveLength(1);
    expect(store.session).toBeNull();
    expect(backend.status()).toMatchObject({ enrolled: false, reenroll: true, link: 'NEEDS_ENROLL' });
    await backend.getSnapshot();
    await backend.presence({ tab_instance_id: '00000000-0000-4000-8000-0000000000aa', observed_channel_login: null, page_visibility: 'VISIBLE', player_state: 'PLAYING' });
    expect(api.enrollBodies).toHaveLength(1); // Refused once: no more silent attempts until the popup join.
    // The popup path still works: name-only is refused, then the invite code is accepted.
    expect(refusesNameOnly(await backend.enroll({ display_name: 'Alice', claimed_twitch_login: null }))).toBe(true);
    expect((await backend.enroll({ invite_code: 'ABCDEFGHJKMN', display_name: 'Alice', claimed_twitch_login: null })).ok).toBe(true);
    expect(backend.status()).toMatchObject({ enrolled: true, reenroll: false });
  });

  it('a 401 that persists after the re-join asks the user to join, and re-joins are rate limited', async () => {
    const api = fakeApi({ rejectEveryToken: true }); // A broken server: accepts enroll, rejects every token.
    const { backend, store } = makeBackend(api);
    api.revoke(tok(1));
    const r = await backend.getOperation('00000000-0000-4000-8000-000000000001');
    expect(r).toMatchObject({ ok: false, kind: 'http', status: 401 });
    expect(store.session).toBeNull();
    expect(backend.status()).toMatchObject({ enrolled: false, reenroll: true, link: 'NEEDS_ENROLL' });
    await backend.getOperation('00000000-0000-4000-8000-000000000002');
    await backend.getSnapshot();
    expect(api.enrollBodies).toHaveLength(1); // No enroll storm.
  });

  it('an explicit sign-out stays signed out (no silent re-join)', async () => {
    const api = fakeApi();
    const { backend, store } = makeBackend(api, { profile: { display_name: 'Alice', claimed_twitch_login: null } });
    await backend.signOut();
    expect(store.profile).toBeNull();
    const r = await backend.getSnapshot();
    expect(r).toMatchObject({ ok: false, status: 401 });
    expect(api.enrollBodies).toHaveLength(0);
    expect(api.calls).toHaveLength(0);
  });
});

describe('popup -> background enroll message', () => {
  function popupHarness() {
    let listener: Parameters<MessageRuntimeLike['onMessage']['addListener']>[0] | null = null;
    const runtime: MessageRuntimeLike = { id: 'ext-id', onMessage: { addListener: (cb) => void (listener = cb) } };
    const inputs: EnrollInput[] = [];
    const adapter = {
      mode: 'LIVE',
      enroll: async (input: EnrollInput) => {
        inputs.push(input);
        return { ok: true, status: 201, body: { me: null } };
      },
    } as unknown as BackendAdapter;
    attachPopupHandler(adapter, runtime);
    const send = (msg: unknown, sender: { id?: string; url?: string }) =>
      new Promise<ApiResult<unknown>>((resolve) => {
        const async = listener!(msg, sender, (r) => resolve(r as ApiResult<unknown>));
        if (async !== true) resolve(undefined as never);
      });
    return { send, inputs };
  }
  const popup = { id: 'ext-id', url: 'chrome-extension://ext-id/popup.html' };

  it('accepts a name-only join (no invite_code) and an empty name', async () => {
    const h = popupHarness();
    expect((await h.send({ t: 'popup', method: 'enroll', params: { display_name: 'Alice', claimed_twitch_login: 'alice_tv' } }, popup)).ok).toBe(true);
    expect((await h.send({ t: 'popup', method: 'enroll', params: {} }, popup)).ok).toBe(true);
    expect(h.inputs).toEqual([
      { invite_code: null, display_name: 'Alice', claimed_twitch_login: 'alice_tv' },
      { invite_code: null, display_name: '', claimed_twitch_login: null },
    ]);
  });

  it('passes an invite code through, and refuses non-text fields and content scripts', async () => {
    const h = popupHarness();
    await h.send({ t: 'popup', method: 'enroll', params: { invite_code: 'ABCD-EFGH-JKMN', display_name: 'Alice' } }, popup);
    expect(h.inputs[0]!.invite_code).toBe('ABCD-EFGH-JKMN');
    expect(await h.send({ t: 'popup', method: 'enroll', params: { invite_code: 42, display_name: 'Alice' } }, popup)).toMatchObject({ ok: false, error: { error: { code: 'VALIDATION_FAILED' } } });
    expect(await h.send({ t: 'popup', method: 'enroll', params: { display_name: 7 } }, popup)).toMatchObject({ ok: false, error: { error: { code: 'VALIDATION_FAILED' } } });
    const fromPage = await h.send({ t: 'popup', method: 'enroll', params: { display_name: 'Eve' } }, { id: 'ext-id', url: 'https://www.twitch.tv/fazegavin1234' });
    expect(fromPage).toMatchObject({ ok: false, error: { error: { code: 'FORBIDDEN' } } });
    expect(h.inputs).toHaveLength(1);
  });
});
