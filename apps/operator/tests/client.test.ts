import { describe, expect, it, vi } from 'vitest';
import { ApiFailure, OperatorClient, checkedId } from '../src/api/client';
import { MKT, NOW, STR, TOKEN, UUID_RE, envelope, json, scriptedFetch, operatorMarket } from './helpers';

function client(handler: Parameters<typeof scriptedFetch>[0], extra: Partial<ConstructorParameters<typeof OperatorClient>[0]> = {}) {
  const f = scriptedFetch(handler);
  const onUnauthorized = vi.fn();
  const onForbidden = vi.fn();
  const c = new OperatorClient({ getToken: () => TOKEN, fetchImpl: f.fetchImpl, onUnauthorized, onForbidden, ...extra });
  return { c, calls: f.calls, onUnauthorized, onForbidden };
}

/** Echo receipt: a well-behaved server returns the operation_id it was sent. */
const echoMarket = (state = 'DRAFT') => (call: { body: Record<string, unknown> | null }) =>
  json(201, { schema_version: 1, operation_id: call.body?.operation_id, replayed: false, market: operatorMarket({ state }) });

async function failureOf(p: Promise<unknown>): Promise<ApiFailure> {
  try {
    await p;
  } catch (e) {
    expect(e).toBeInstanceOf(ApiFailure);
    return e as ApiFailure;
  }
  throw new Error('expected a failure');
}

describe('operation ids', () => {
  it('sends a fresh canonical UUID operation_id for every new intent', async () => {
    const { c, calls } = client(echoMarket());
    const a = await c.createMarket({ question: 'Q?', yes_label: 'Yes', no_label: 'No', close_in_s: 60, resolve_in_s: 120 });
    const b = await c.createMarket({ question: 'Q?', yes_label: 'Yes', no_label: 'No', close_in_s: 60, resolve_in_s: 120 });
    expect(calls).toHaveLength(2);
    const [id1, id2] = calls.map((x) => x.body?.operation_id as string);
    expect(id1).toMatch(UUID_RE);
    expect(id2).toMatch(UUID_RE);
    expect(id1).not.toBe(id2);
    expect(a.operationId).toBe(id1);
    expect(b.operationId).toBe(id2);
    expect(a.replayed).toBe(false);
    expect(calls[0].url).toBe('/v1/operator/markets');
    expect(calls[0].method).toBe('POST');
  });

  it('retries an unknown outcome with the SAME operation_id and identical body', async () => {
    let n = 0;
    const { c, calls } = client((call) => (++n === 1 ? json(500, envelope('INTERNAL_ERROR', 'boom')) : echoMarket('VOID')(call)));
    const failure = await failureOf(c.voidMarket(MKT, 'operator test'));
    expect(failure.outcomeUnknown).toBe(true);
    expect(failure.retrySameOperation).toBe(true);
    expect(failure.pending).not.toBeNull();
    const ok = await c.retry(failure.pending!);
    expect(calls).toHaveLength(2);
    expect(calls[1].body).toEqual(calls[0].body);
    expect(ok.operationId).toBe(calls[0].body?.operation_id);
    expect(calls[0].body).toEqual({ note: 'operator test', operation_id: ok.operationId });
  });

  it('never reports success unless the 2xx body echoes this operation_id', async () => {
    const { c } = client(() => json(200, { schema_version: 1, operation_id: '00000000-0000-4000-8000-000000000000', replayed: false }));
    const failure = await failureOf(c.openMarket(MKT));
    expect(failure.kind).toBe('bad_response');
    expect(failure.outcomeUnknown).toBe(true);
    expect(failure.retrySameOperation).toBe(true);
  });

  it('treats an unparseable 2xx mutation body as an unknown outcome', async () => {
    const { c } = client(() => new Response('<html>ok</html>', { status: 200 }));
    const failure = await failureOf(c.openMarket(MKT));
    expect(failure.kind).toBe('bad_response');
    expect(failure.outcomeUnknown).toBe(true);
  });
});

describe('§9.10 error envelopes', () => {
  it('parses a typed 409 as a definitive refusal (no same-key retry)', async () => {
    const { c } = client(() =>
      json(409, envelope('STALE_MARKET', 'Another market in this run is not terminal yet.', {
        details: { current_market_id: MKT, current_rules_version: 1 },
      })),
    );
    const failure = await failureOf(c.openMarket(MKT));
    expect(failure.kind).toBe('envelope');
    expect(failure.status).toBe(409);
    expect(failure.code).toBe('STALE_MARKET');
    expect(failure.info?.details).toEqual({ current_market_id: MKT, current_rules_version: 1 });
    expect(failure.info?.request_id).toMatch(/^req_/);
    expect(failure.outcomeUnknown).toBe(false);
    expect(failure.retrySameOperation).toBe(false);
    expect(failure.pending).toBeNull();
  });

  it('keeps VALIDATION_FAILED field details and the echoed operation_id', async () => {
    const { c, calls } = client((call) =>
      json(422, envelope('VALIDATION_FAILED', 'Invalid fixture market timing.', {
        operation_id: call.body?.operation_id,
        details: { fields: [{ loc: ['close_in_s'], msg: 'must be at least 30 s (min_lead_ms)' }] },
      })),
    );
    const failure = await failureOf(c.createMarket({ question: 'Q', yes_label: 'Y', no_label: 'N', close_in_s: 5, resolve_in_s: 60 }));
    expect(failure.code).toBe('VALIDATION_FAILED');
    expect(failure.operationId).toBe(calls[0].body?.operation_id);
    expect(failure.outcomeUnknown).toBe(false);
  });

  it('RATE_LIMITED allows a same-key retry but is not an unknown outcome', async () => {
    const { c } = client(() => json(429, envelope('RATE_LIMITED', 'slow down', { retry_after_ms: 4000 })));
    const failure = await failureOf(c.createViewerInvite());
    expect(failure.code).toBe('RATE_LIMITED');
    expect(failure.info?.retry_after_ms).toBe(4000);
    expect(failure.retrySameOperation).toBe(true);
    expect(failure.outcomeUnknown).toBe(false);
  });

  it('keeps unknown codes (e.g. worker-only STALE_EPOCH) as strings', async () => {
    const { c } = client(() => json(409, envelope('STALE_EPOCH', 'old epoch')));
    const failure = await failureOf(c.health());
    expect(failure.code).toBe('STALE_EPOCH');
  });

  it('a non-envelope 502 on a mutation is an unknown outcome', async () => {
    const { c } = client(() => new Response('Bad Gateway', { status: 502 }));
    const failure = await failureOf(c.resetRun(STR));
    expect(failure.kind).toBe('bad_response');
    expect(failure.status).toBe(502);
    expect(failure.outcomeUnknown).toBe(true);
    expect(failure.pending?.body).toEqual({ stream_id: STR });
  });

  it('a network error on a mutation is an unknown outcome; on a read it is not', async () => {
    const { c } = client(() => Promise.reject(new TypeError('Failed to fetch')));
    const m = await failureOf(c.openMarket(MKT));
    expect(m.kind).toBe('network');
    expect(m.outcomeUnknown).toBe(true);
    const r = await failureOf(c.health());
    expect(r.kind).toBe('network');
    expect(r.outcomeUnknown).toBe(false);
  });

  it('a timeout aborts the request and leaves a mutation outcome unknown', async () => {
    const f = scriptedFetch(() => new Promise<Response>(() => undefined));
    const hang = (async (input: RequestInfo | URL, init?: RequestInit) =>
      new Promise<Response>((_, reject) => {
        void f.fetchImpl(input, init);
        init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
      })) as typeof fetch;
    const c = new OperatorClient({ getToken: () => TOKEN, fetchImpl: hang, timeoutMs: 20 });
    const failure = await failureOf(c.openMarket(MKT));
    expect(failure.kind).toBe('timeout');
    expect(failure.outcomeUnknown).toBe(true);
    expect(failure.pending?.operationId).toMatch(UUID_RE);
  });
});

describe('authentication', () => {
  it('sends the token only as a Bearer header, never in the URL', async () => {
    const { c, calls } = client(() => json(200, { schema_version: 1, server_time_utc: NOW }));
    await c.health();
    expect(calls[0].headers.Authorization).toBe(`Bearer ${TOKEN}`);
    expect(calls[0].url).toBe('/v1/operator/health');
    expect(calls[0].url).not.toContain(TOKEN);
  });

  it('a 401 on an authenticated call triggers onUnauthorized', async () => {
    const { c, onUnauthorized } = client(() => json(401, envelope('UNAUTHENTICATED', 'Session is invalid, expired or revoked.')));
    const failure = await failureOf(c.health());
    expect(failure.status).toBe(401);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it('a 401 from enroll (bad invite) does not count as a lost session', async () => {
    const { c, calls, onUnauthorized } = client(() => json(401, envelope('UNAUTHENTICATED', 'bad code')));
    const failure = await failureOf(c.enroll({ invite_code: 'ABCDEFGHJKMN', display_name: 'Op', device_id: crypto.randomUUID() }));
    expect(failure.status).toBe(401);
    expect(onUnauthorized).not.toHaveBeenCalled();
    expect(calls[0].headers.Authorization).toBeUndefined();
    expect(calls[0].body?.claimed_twitch_login).toBeNull();
  });

  it('with no token, an authenticated call never reaches the network', async () => {
    const f = scriptedFetch(() => json(200, {}));
    const onUnauthorized = vi.fn();
    const c = new OperatorClient({ getToken: () => null, fetchImpl: f.fetchImpl, onUnauthorized });
    await failureOf(c.health());
    expect(f.calls).toHaveLength(0);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it('a 403 FORBIDDEN on an operator route triggers onForbidden', async () => {
    const { c, onForbidden } = client(() => json(403, envelope('FORBIDDEN', 'Operator session required.')));
    await failureOf(c.health());
    expect(onForbidden).toHaveBeenCalledTimes(1);
  });
});

describe('path safety', () => {
  it('refuses malformed server ids before any request', async () => {
    const { c, calls } = client(() => json(200, {}));
    expect(() => checkedId('mkt', '../operator/runs/reset')).toThrow();
    await expect(c.openMarket('mkt_../../x')).rejects.toThrow(/invalid mkt id/);
    await expect(c.evidenceImage('evd_x')).rejects.toThrow(/invalid evd id/);
    expect(calls).toHaveLength(0);
  });
});
