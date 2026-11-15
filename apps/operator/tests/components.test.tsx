import { act } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from '../src/App';
import { OperatorClient } from '../src/api/client';
import { SESSION_STORAGE_KEY } from '../src/api/session';
import { InvitePanel } from '../src/ui/InvitePanel';
import { MarketPanel } from '../src/ui/MarketPanel';
import { RunPanel } from '../src/ui/RunPanel';
import { SignIn } from '../src/ui/SignIn';
import {
  MKT,
  NOW,
  RUN,
  STR,
  TOKEN,
  UUID_RE,
  byText,
  click,
  envelope,
  flush,
  healthBody,
  json,
  mount,
  operatorMarket,
  scriptedFetch,
  typeInto,
  waitFor,
  type Call,
  type Mounted,
} from './helpers';

let mounted: Mounted | null = null;
afterEach(() => {
  mounted?.unmount();
  mounted = null;
  sessionStorage.clear();
  localStorage.clear();
  window.location.hash = '';
  vi.unstubAllGlobals();
});

function makeClient(handler: (call: Call) => Response | Promise<Response>) {
  const f = scriptedFetch(handler);
  return { client: new OperatorClient({ getToken: () => TOKEN, fetchImpl: f.fetchImpl }), calls: f.calls };
}

function enrollBody(role: string) {
  return {
    schema_version: 1,
    session_token: TOKEN,
    session_id: `ses_${'e'.repeat(32)}`,
    expires_at_utc: '2099-01-01T00:00:00.000Z',
    me: {
      server_time_utc: NOW,
      user: { user_id: `usr_${'f'.repeat(32)}`, display_name: 'Op', claimed_twitch_login: null, role },
      session: { session_id: `ses_${'e'.repeat(32)}`, expires_at_utc: '2099-01-01T00:00:00.000Z' },
      current_stream: null,
      wallet: null,
    },
  };
}

async function signInWith(role: string | 401) {
  const { client, calls } = makeClient(() => (role === 401 ? json(401, envelope('UNAUTHENTICATED')) : json(201, enrollBody(role))));
  const onSignedIn = vi.fn();
  mounted = await mount(<SignIn client={client} notice={null} onSignedIn={onSignedIn} />);
  const c = mounted.container;
  await typeInto(c.querySelector('input[name="invite_code"]'), 'abcd-efgh-jkmn');
  await typeInto(c.querySelector('input[name="display_name"]'), 'Operator One');
  await click(byText(c, 'button', 'Sign in'));
  await flush();
  return { c, calls, onSignedIn };
}

describe('SignIn', () => {
  it('enrolls with the normalized invite and accepts an OPERATOR session', async () => {
    const { calls, onSignedIn } = await signInWith('OPERATOR');
    expect(calls[0].url).toBe('/v1/enroll');
    expect(calls[0].body?.invite_code).toBe('ABCDEFGHJKMN');
    expect(calls[0].body?.device_id).toMatch(UUID_RE);
    expect(onSignedIn).toHaveBeenCalledTimes(1);
    expect(onSignedIn.mock.calls[0][0].token).toBe(TOKEN);
  });

  it('refuses a non-OPERATOR session and never stores its token', async () => {
    const { c, onSignedIn } = await signInWith('VIEWER');
    expect(onSignedIn).not.toHaveBeenCalled();
    expect(c.textContent).toContain('enrolled a VIEWER account');
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
  });

  it('shows the indistinguishable bad-invite message on 401', async () => {
    const { c, onSignedIn } = await signInWith(401);
    expect(onSignedIn).not.toHaveBeenCalled();
    expect(c.textContent).toContain('invalid, already used, or expired');
  });
});

describe('MarketPanel', () => {
  it('uses a fresh operation_id for every Create click and shows the receipt only after the server answers', async () => {
    const { client, calls } = makeClient((call) =>
      json(201, { schema_version: 1, operation_id: call.body?.operation_id, replayed: false, market: operatorMarket({ state: 'DRAFT' }) }),
    );
    const onChanged = vi.fn();
    mounted = await mount(<MarketPanel client={client} onChanged={onChanged} health={healthBody() as never} serverNowMs={null} settleReasonField={null} />);
    const c = mounted.container;
    await typeInto(c.querySelector('form[aria-label="Create fixture market"] input'), 'Will FaZeGavin win?');
    expect(c.querySelector('[data-testid="receipt"]')).toBeNull();
    await click(byText(c, 'button', 'Create draft'));
    await waitFor(() => c.querySelector('[data-testid="receipt"]'));
    await click(byText(c, 'button', 'Create draft'));
    await flush();
    expect(calls).toHaveLength(2);
    const ids = calls.map((x) => x.body?.operation_id);
    expect(ids[0]).toMatch(UUID_RE);
    expect(ids[1]).toMatch(UUID_RE);
    expect(ids[0]).not.toBe(ids[1]);
    expect(calls[0].body).toMatchObject({ question: 'Will FaZeGavin win?', yes_label: 'Yes', no_label: 'No', close_in_s: 60, resolve_in_s: 120 });
    expect(onChanged).toHaveBeenCalledTimes(2);
  });

  it('settles only after a confirm with a reason, and shows typed errors instead of success', async () => {
    const { client, calls } = makeClient(() =>
      json(409, envelope('MARKET_CLOSED', 'The resolution deadline has passed; the market will VOID.', {
        details: { state: 'EVALUATING', close_at_utc: NOW, reason: 'DEADLINE' },
      })),
    );
    const health = healthBody({ markets: [operatorMarket({ state: 'EVALUATING' })] });
    mounted = await mount(<MarketPanel client={client} onChanged={() => undefined} health={health as never} serverNowMs={null} settleReasonField={null} />);
    const c = mounted.container;
    expect(c.querySelector('[data-testid="pools"]')?.textContent).toContain('$12.00');
    expect(c.querySelector('[data-testid="simulated"]')?.textContent).toContain('Simulated (bot) stakes: $0.00');
    await click(byText(c, 'button', 'Settle YES…'));
    const confirm = byText(c, 'button', 'Confirm settle YES') as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    expect(calls).toHaveLength(0);
    await typeInto(c.querySelector('[data-testid="confirm-box"] textarea'), 'Gavin won on stream');
    expect(confirm.disabled).toBe(false);
    await click(confirm);
    await waitFor(() => c.querySelector('[data-testid="error-notice"]'));
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(`/v1/operator/markets/${MKT}/settle`);
    expect(calls[0].body).toEqual({ winning_side: 'YES', note: 'Gavin won on stream', operation_id: calls[0].body?.operation_id });
    const notice = c.querySelector('[data-testid="error-notice"]')!.textContent!;
    expect(notice).toContain('MARKET_CLOSED');
    expect(notice).toContain('HTTP 409');
    expect(notice).toContain('deadline has passed');
    expect(c.querySelector('[data-testid="receipt"]')).toBeNull();
  });

  it('sends the settle reason when the API advertises a field for it', async () => {
    const { client, calls } = makeClient((call) =>
      json(200, { schema_version: 1, operation_id: call.body?.operation_id, replayed: false, market: operatorMarket({ state: 'SETTLED', winning_side: 'NO' }) }),
    );
    const health = healthBody({ markets: [operatorMarket({ state: 'EVALUATING' })] });
    mounted = await mount(<MarketPanel client={client} onChanged={() => undefined} health={health as never} serverNowMs={null} settleReasonField="note" />);
    const c = mounted.container;
    await click(byText(c, 'button', 'Settle NO…'));
    await typeInto(c.querySelector('[data-testid="confirm-box"] textarea'), 'Neville won');
    await click(byText(c, 'button', 'Confirm settle NO'));
    await waitFor(() => c.querySelector('[data-testid="receipt"]'));
    expect(calls[0].body).toMatchObject({ winning_side: 'NO', note: 'Neville won' });
    expect(c.querySelector('[data-testid="receipt"]')!.textContent).toContain('SETTLED');
  });
  it('keeps the settle receipt visible when the polled market moves to SETTLED', async () => {
    const { client } = makeClient((call) =>
      json(200, { schema_version: 1, operation_id: call.body?.operation_id, replayed: false, market: operatorMarket({ state: 'SETTLED', winning_side: 'YES' }) }),
    );
    const props = { client, onChanged: () => undefined, serverNowMs: null, settleReasonField: null };
    mounted = await mount(<MarketPanel {...props} health={healthBody({ markets: [operatorMarket({ state: 'EVALUATING' })] }) as never} />);
    const c = mounted.container;
    await click(byText(c, 'button', 'Settle YES…'));
    await typeInto(c.querySelector('[data-testid="confirm-box"] textarea'), 'Gavin won on stream');
    await click(byText(c, 'button', 'Confirm settle YES'));
    await waitFor(() => c.querySelector('[data-testid="receipt"]'));
    await act(async () => {
      mounted!.root.render(
        <MarketPanel {...props} health={healthBody({ markets: [operatorMarket({ state: 'SETTLED', winning_side: 'YES' })] }) as never} />,
      );
    });
    expect(c.querySelector('[data-market-state="SETTLED"] [data-testid="receipt"]')?.textContent).toContain('SETTLED');
  });
});

describe('InvitePanel', () => {
  it('shows a new code once with the single-use note; a replay shows no code', async () => {
    let n = 0;
    const { client } = makeClient((call) =>
      json(++n === 1 ? 201 : 200, {
        schema_version: 1,
        operation_id: call.body?.operation_id,
        replayed: n !== 1,
        invite: { invite_id: `inv_${String(n).repeat(32)}`, role: 'VIEWER', is_bot: false, bind_user_id: null, expires_at_utc: '2026-11-16T04:00:00.000Z' },
        invite_code: n === 1 ? 'ABCD-EFGH-JKMN' : null,
      }),
    );
    mounted = await mount(<InvitePanel client={client} />);
    const c = mounted.container;
    await click(byText(c, 'button', 'Create viewer invite'));
    await waitFor(() => c.querySelector('[data-testid="invite-code"]'));
    const card = c.querySelector('[data-testid="invite-code"]')!.textContent!;
    expect(card).toContain('ABCD-EFGH-JKMN');
    expect(card).toContain('Single use');
    expect(card).toContain('valid 24 h');
    await click(byText(c, 'button', 'Create viewer invite'));
    await flush();
    expect(c.querySelectorAll('[data-testid="invite-code"]')).toHaveLength(1);
    expect(c.textContent).toContain('cannot be shown again');
    await click(byText(c, 'button', 'Hide'));
    expect(c.querySelectorAll('[data-testid="invite-code"]')).toHaveLength(0);
  });
});

describe('RunPanel', () => {
  it('needs two confirmations before resetting', async () => {
    const { client, calls } = makeClient((call) =>
      json(201, {
        schema_version: 1,
        operation_id: call.body?.operation_id,
        replayed: false,
        archived_stream_session_id: RUN,
        stream_session_id: `run_${'9'.repeat(32)}`,
        voided_market_id: MKT,
        stream: healthBody().stream,
      }),
    );
    const health = healthBody({ markets: [operatorMarket({ state: 'OPEN' })] });
    mounted = await mount(<RunPanel client={client} health={health as never} onChanged={() => undefined} />);
    const c = mounted.container;
    await click(byText(c, 'button', 'Reset run…'));
    expect(c.querySelector('[data-testid="reset-explain"]')!.textContent).toContain('RUN_RESET');
    await click(byText(c, 'button', 'Continue'));
    const go = byText(c, 'button', 'Reset run now') as HTMLButtonElement;
    expect(go.disabled).toBe(true);
    await typeInto(c.querySelector('form.confirm input'), 'reset');
    expect(go.disabled).toBe(true);
    await typeInto(c.querySelector('form.confirm input'), 'RESET');
    expect(go.disabled).toBe(false);
    await click(go);
    await waitFor(() => c.querySelector('[data-testid="receipt"]'));
    expect(calls).toHaveLength(1);
    expect(calls[0].body).toEqual({ stream_id: STR, operation_id: calls[0].body?.operation_id });
    expect(calls[0].body?.operation_id).toMatch(UUID_RE);
    expect(c.querySelector('[data-testid="receipt"]')!.textContent).toContain('voided');
  });
});

const STORED = JSON.stringify({
  token: TOKEN,
  session_id: `ses_${'e'.repeat(32)}`,
  expires_at_utc: '2099-01-01T00:00:00.000Z',
  user_id: `usr_${'f'.repeat(32)}`,
  display_name: 'Op',
});
const NEW_TOKEN = 'fzs_freshtokenfreshtokenfresh0000';
const OPEN_PATH = '/v1/open/operator-session';
const AI_APPROVAL = { ai_mode: 'APPROVAL', effective_ai_mode: 'APPROVAL', allow_automatic: false, pending_candidates: 0, pending_resolutions: 0 };

function openSessionBody(token = NEW_TOKEN) {
  return { ...enrollBody('OPERATOR'), session_token: token };
}

/** Records whether the sign-in form (invite code field) EVER appears in the container. */
function watchForSignInForm(container: HTMLElement) {
  const seen = { form: false };
  const check = () => {
    if (container.querySelector('input[name="invite_code"]')) seen.form = true;
  };
  const obs = new MutationObserver(check);
  obs.observe(container, { childList: true, subtree: true });
  return { seen, stop: () => obs.disconnect(), check };
}

describe('App (D35 open access and invite mode)', () => {
  it('INVITE mode: a 401 returns to the sign-in form and forgets the token', async () => {
    sessionStorage.setItem(SESSION_STORAGE_KEY, STORED);
    const seen: string[] = [];
    vi.stubGlobal('fetch', async (input: RequestInfo | URL) => {
      const url = String(input);
      seen.push(url);
      if (url === OPEN_PATH) return json(404, envelope('NOT_FOUND', 'Not found.'));
      if (url === '/v1/me') return json(200, { schema_version: 1, ...enrollBody('OPERATOR').me });
      if (url === '/openapi.json') return json(200, { paths: {} });
      return json(401, envelope('UNAUTHENTICATED', 'Session is invalid, expired or revoked.'));
    });
    mounted = await mount(<App />);
    const c = mounted.container;
    await waitFor(() => c.querySelector('input[name="invite_code"]'));
    expect(seen).toContain('/v1/operator/health');
    expect(seen).toContain(OPEN_PATH); // tried a silent re-open first; 404 = invite mode
    expect(c.textContent).toContain('(401)');
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
  });

  it('OPEN mode: a 401 mid-session silently re-opens, the request is retried once, and no form is rendered', async () => {
    sessionStorage.setItem(SESSION_STORAGE_KEY, STORED);
    const calls: { url: string; auth: string | undefined; body: unknown }[] = [];
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const auth = (init?.headers as Record<string, string> | undefined)?.Authorization;
      calls.push({ url, auth, body: typeof init?.body === 'string' ? JSON.parse(init.body) : null });
      if (url === OPEN_PATH) return json(201, openSessionBody());
      if (url === '/v1/me') return json(200, { schema_version: 1, ...enrollBody('OPERATOR').me });
      // The stored session has expired on the server: every call with the old token is a 401.
      if (auth === `Bearer ${TOKEN}`) return json(401, envelope('UNAUTHENTICATED', 'Session is invalid, expired or revoked.'));
      if (url === '/v1/operator/health') return json(200, healthBody({ ai: AI_APPROVAL }));
      if (url.startsWith('/v1/operator/candidates')) return json(200, { schema_version: 1, server_time_utc: NOW, candidates: [] });
      return json(404, envelope('NOT_FOUND'));
    });
    mounted = await mount(<App />);
    const w = watchForSignInForm(mounted.container);
    const c = mounted.container;
    await waitFor(() => c.querySelector('[data-testid="demo-view"]') && c.textContent?.includes('Waiting for the AI to spot a bet'));
    w.check();
    w.stop();
    expect(w.seen.form).toBe(false);
    expect(c.querySelector('input[name="invite_code"]')).toBeNull();
    const opens = calls.filter((x) => x.url === OPEN_PATH);
    expect(opens).toHaveLength(1);
    expect((opens[0].body as { device_id: string }).device_id).toMatch(UUID_RE);
    const health = calls.filter((x) => x.url === '/v1/operator/health');
    expect(health[0].auth).toBe(`Bearer ${TOKEN}`); // first try: old token, 401
    expect(health[1].auth).toBe(`Bearer ${NEW_TOKEN}`); // retried once with the fresh session
    expect(JSON.parse(sessionStorage.getItem(SESSION_STORAGE_KEY)!).token).toBe(NEW_TOKEN);
  });

  it('OPEN mode: with no stored session it signs in through the open route and reuses one device_id', async () => {
    const devices: string[] = [];
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === OPEN_PATH) {
        devices.push(JSON.parse(String(init?.body)).device_id);
        return json(201, openSessionBody());
      }
      if (url === '/v1/operator/health') return json(200, healthBody());
      if (url.startsWith('/v1/operator/candidates')) return json(200, { schema_version: 1, server_time_utc: NOW, candidates: [] });
      return json(404, envelope('NOT_FOUND'));
    });
    mounted = await mount(<App />);
    let c = mounted.container;
    await waitFor(() => c.querySelector('[data-testid="demo-view"]'));
    expect(c.querySelector('input[name="invite_code"]')).toBeNull();
    expect(JSON.parse(sessionStorage.getItem(SESSION_STORAGE_KEY)!).token).toBe(NEW_TOKEN);
    mounted.unmount();
    sessionStorage.clear(); // a new tab: no session, same browser (device id in localStorage)
    mounted = await mount(<App />);
    c = mounted.container;
    await waitFor(() => c.querySelector('[data-testid="demo-view"]'));
    expect(devices).toHaveLength(2);
    expect(devices[0]).toMatch(UUID_RE);
    expect(devices[1]).toBe(devices[0]);
  });

  it('OPEN mode: a network failure on the open route shows Connecting, never the form', async () => {
    vi.stubGlobal('fetch', async (input: RequestInfo | URL) => {
      if (String(input) === OPEN_PATH) throw new TypeError('Failed to fetch');
      return json(404, envelope('NOT_FOUND'));
    });
    mounted = await mount(<App />);
    const c = mounted.container;
    await waitFor(() => c.textContent?.includes("Can't reach the server. Retrying…"));
    expect(c.querySelector('input[name="invite_code"]')).toBeNull();
  });

  it('INVITE mode: a restored non-OPERATOR session is discarded and the sign-in form is shown', async () => {
    sessionStorage.setItem(SESSION_STORAGE_KEY, STORED);
    vi.stubGlobal('fetch', async (input: RequestInfo | URL) => {
      if (String(input) === OPEN_PATH) return json(404, envelope('NOT_FOUND'));
      return json(200, { schema_version: 1, ...enrollBody('VIEWER').me });
    });
    mounted = await mount(<App />);
    const c = mounted.container;
    await waitFor(() => c.querySelector('input[name="invite_code"]'));
    expect(c.textContent).toContain('VIEWER account');
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
  });

  it('OPEN mode: a restored non-OPERATOR session is discarded and replaced silently (no form)', async () => {
    sessionStorage.setItem(SESSION_STORAGE_KEY, STORED);
    vi.stubGlobal('fetch', async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === OPEN_PATH) return json(201, openSessionBody());
      if (url === '/v1/me') return json(200, { schema_version: 1, ...enrollBody('VIEWER').me });
      if (url === '/v1/operator/health') return json(200, healthBody());
      if (url.startsWith('/v1/operator/candidates')) return json(200, { schema_version: 1, server_time_utc: NOW, candidates: [] });
      return json(404, envelope('NOT_FOUND'));
    });
    mounted = await mount(<App />);
    const w = watchForSignInForm(mounted.container);
    const c = mounted.container;
    await waitFor(() => c.querySelector('[data-testid="demo-view"]'));
    w.check();
    w.stop();
    expect(w.seen.form).toBe(false);
    expect(JSON.parse(sessionStorage.getItem(SESSION_STORAGE_KEY)!).token).toBe(NEW_TOKEN);
  });
});
