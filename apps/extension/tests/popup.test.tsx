// Live popup (D35): optional name, one tap on Join, invite field only after the server refuses name-only enroll.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it } from 'vitest';
import { LiveEnroll, type PopupAsk } from '../entrypoints/popup/main';
import type { ApiResult, BackgroundStatus } from '../src/api/types';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const status = (enrolled: boolean, displayName: string | null = null): BackgroundStatus => ({
  mode: 'LIVE',
  link: enrolled ? 'IDLE' : 'NEEDS_ENROLL',
  enrolled,
  reenroll: false,
  displayName,
  role: enrolled ? 'VIEWER' : null,
  apiBase: 'http://127.0.0.1:8000',
  channel: 'fazegavin1234',
  message: null,
});
const envelope = (code: string, details: unknown = null) => ({
  schema_version: 1 as const,
  error: { code, message: 'x', retryable: false, retry_after_ms: null, request_id: `req_${'c'.repeat(32)}`, operation_id: null, details },
  server_time_utc: '2026-11-15T06:00:00.000Z',
});
const refused = (status: number, code: string, details: unknown = null): ApiResult<unknown> => ({ ok: false, kind: 'http', status, error: envelope(code, details) as never });
const joined = (name: string): ApiResult<unknown> => ({ ok: true, status: 201, body: { me: { user: { display_name: name, claimed_twitch_login: null } } } });

function fakeBackground(enrollAnswers: ApiResult<unknown>[]) {
  const enrolls: Record<string, unknown>[] = [];
  let enrolled = false;
  let name: string | null = null;
  const ask = (async (method: string, params?: unknown) => {
    if (method === 'status') return { ok: true, status: 200, body: status(enrolled, name) };
    if (method === 'enroll') {
      enrolls.push(params as Record<string, unknown>);
      const answer = enrollAnswers.shift() ?? refused(503, 'CAPABILITY_UNAVAILABLE');
      if (answer.ok) {
        enrolled = true;
        name = String((params as { display_name: string }).display_name);
      }
      return answer;
    }
    return { ok: true, status: 200, body: status(enrolled, name) };
  }) as PopupAsk;
  return { ask, enrolls };
}

let root: Root | null = null;
let container: HTMLElement | null = null;
afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  root = null;
  container = null;
});

async function render(ask: PopupAsk) {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => root!.render(<LiveEnroll askBackground={ask} />));
  await flush();
  return container;
}
async function flush() {
  for (let i = 0; i < 4; i++) await act(async () => new Promise((r) => setTimeout(r, 0)));
}
async function type(el: Element | null, value: string) {
  if (!el) throw new Error('no input');
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}
async function pressJoin(c: HTMLElement) {
  const button = [...c.querySelectorAll('button')].find((b) => b.textContent === 'Join');
  if (!button) throw new Error('no Join button');
  await act(async () => button.click());
  await flush();
}

describe('live popup (D35)', () => {
  it('asks only for an optional name and Twitch name; one tap on Join joins name-only with a default name', async () => {
    const bg = fakeBackground([joined('Viewer 0042')]);
    const c = await render(bg.ask);
    const labels = [...c.querySelectorAll('label')].map((l) => l.firstChild?.textContent?.trim());
    expect(labels).toEqual(['Your name', 'Twitch name (optional)']);
    expect(c.querySelector('input[name="invite_code"]')).toBeNull();
    const button = [...c.querySelectorAll('button')].find((b) => b.textContent === 'Join')!;
    expect(button.disabled).toBe(false); // Name is optional.
    await pressJoin(c);
    expect(bg.enrolls).toHaveLength(1);
    expect(bg.enrolls[0]!.display_name).toMatch(/^Viewer \d{4}$/);
    expect('invite_code' in bg.enrolls[0]!).toBe(false);
    expect(c.textContent).toContain('Signed in as');
    expect(c.textContent).not.toMatch(/MOCK|DEMO/); // D31: live popup stays clean.
  });

  it('reveals the invite field only after a 401, keeps the same name, and retries with the code', async () => {
    const bg = fakeBackground([refused(401, 'UNAUTHENTICATED'), refused(401, 'UNAUTHENTICATED'), joined('Alice')]);
    const c = await render(bg.ask);
    await type(c.querySelector('input[name="display_name"]'), 'Alice');
    await pressJoin(c);
    expect(bg.enrolls[0]).toEqual({ display_name: 'Alice', claimed_twitch_login: null });
    expect(c.querySelector('input[name="invite_code"]')).not.toBeNull();
    expect(c.textContent).toContain('This server needs an invite code.');
    await type(c.querySelector('input[name="invite_code"]'), 'abcd-efgh-jkmn');
    await pressJoin(c);
    expect(bg.enrolls[1]).toEqual({ display_name: 'Alice', claimed_twitch_login: null, invite_code: 'abcd-efgh-jkmn' });
    expect(c.textContent).toContain('That invite code is invalid, used or expired.');
    await pressJoin(c);
    expect(bg.enrolls).toHaveLength(3);
    expect(c.textContent).toContain('Signed in as');
  });

  it('an older invite-only API (VALIDATION_FAILED naming invite_code) also reveals the field', async () => {
    const bg = fakeBackground([refused(400, 'VALIDATION_FAILED', { fields: [{ loc: ['body', 'invite_code'], msg: 'Field required' }] })]);
    const c = await render(bg.ask);
    await pressJoin(c);
    expect(c.querySelector('input[name="invite_code"]')).not.toBeNull();
  });

  it('other failures never show an invite prompt', async () => {
    const bg = fakeBackground([{ ok: false, kind: 'unknown', message: 'offline' }, refused(429, 'RATE_LIMITED')]);
    const c = await render(bg.ask);
    await pressJoin(c);
    expect(c.textContent).toContain('Could not reach the FaZeTime API');
    await pressJoin(c);
    expect(c.querySelector('input[name="invite_code"]')).toBeNull();
    expect(c.textContent).not.toMatch(/invite/i);
  });
});
