// Popup.
// - mock builds (P1-B): display name + optional claimed Twitch login, stored locally.
// - live builds (P2, D35 open access): optional "Your name" + optional Twitch name + one tap on Join (an empty
//   name becomes "Viewer 1234"). The BACKGROUND calls POST /v1/enroll name-only; only if the server refuses
//   that (401, invite-only) does this popup reveal an "Invite code" field and retry with it. The background
//   keeps the session token (the popup never sees it) and later re-joins silently with the same name.
// The Twitch login is a label, NOT verified identity. No phone field (D16), no card fields, ever.
import { StrictMode, useEffect, useState, type FormEvent } from 'react';
import { createRoot } from 'react-dom/client';
import { browser } from 'wxt/browser';
import { CLAIMED_TWITCH_LOGIN_PATTERN, INVITE_CODE_PATTERN, normalizeInviteCode, type Me } from '@fazetime/contracts';
import type { ApiResult, BackgroundStatus } from '../../src/api/types';
import { FAZETIME_MODE } from '../../src/config';
import { defaultDisplayName, refusesNameOnly } from '../../src/lib/join';
import { describeError } from '../../src/state/errorCopy';
import { wxtKV } from '../../src/storage';
import { PROFILE_KEY, type Profile } from '../../src/ui/hooks';
import './style.css';

export function validateProfile(displayName: string, login: string): string | null {
  const name = displayName.trim();
  if ([...name].length < 1 || [...name].length > 32) return 'Display name must be 1 to 32 characters.';
  if (login.trim() !== '' && !CLAIMED_TWITCH_LOGIN_PATTERN.test(login.trim()))
    return 'Twitch login may only use letters, numbers and underscores (up to 25).';
  return null;
}

export type PopupAsk = <T>(method: 'status' | 'enroll' | 'signout', params?: unknown) => Promise<ApiResult<T>>;

const ask: PopupAsk = <T,>(method: 'status' | 'enroll' | 'signout', params?: unknown) =>
  browser.runtime.sendMessage({ t: 'popup', method, params }) as Promise<ApiResult<T>>;


function Header({ badge }: { badge: string | null }) {
  return (
    <header>
      <h1>
        FaZe<b>Time</b>
      </h1>
      {badge && <span className="mock">{badge}</span>}
    </header>
  );
}

function MockProfile() {
  const [name, setName] = useState('');
  const [login, setLogin] = useState('');
  const [status, setStatus] = useState<string | null>(null);
  useEffect(() => {
    void wxtKV.get<Profile>(PROFILE_KEY).then((p) => {
      if (p) {
        setName(p.display_name);
        setLogin(p.claimed_twitch_login ?? '');
      }
    });
  }, []);
  const error = validateProfile(name, login);
  const save = async () => {
    if (error) return;
    await wxtKV.set<Profile>(PROFILE_KEY, { display_name: name.trim(), claimed_twitch_login: login.trim() || null });
    setStatus('Saved on this browser.');
  };
  return (
    <main>
      <Header badge="MOCK" />
      <p className="fine">Demo build with local mock data only. No account, no backend, no real money.</p>
      <label>
        Display name
        <input value={name} maxLength={64} onChange={(e) => (setName(e.target.value), setStatus(null))} placeholder="PixelPilot" />
      </label>
      <label>
        Twitch login (optional)
        <input value={login} maxLength={25} onChange={(e) => (setLogin(e.target.value), setStatus(null))} placeholder="your_twitch_name" />
        <span className="fine">Not verified. It is only a label and does not log you in.</span>
      </label>
      {error && name !== '' && <p className="err">{error}</p>}
      <button type="button" disabled={error !== null} onClick={() => void save()}>
        Save profile
      </button>
      {status && <p className="ok">{status}</p>}
    </main>
  );
}

export function LiveEnroll({ askBackground = ask }: { askBackground?: PopupAsk } = {}) {
  const [st, setSt] = useState<BackgroundStatus | null>(null);
  const [name, setName] = useState('');
  const [login, setLogin] = useState('');
  // Used when "Your name" is left empty; fixed for this popup so an invite retry keeps the same name.
  const [fallbackName] = useState(defaultDisplayName);
  // Hidden until the server says it is invite-only (401 on the name-only join).
  const [needCode, setNeedCode] = useState(false);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const refresh = () => askBackground<BackgroundStatus>('status').then((r) => r?.ok && setSt(r.body));
  useEffect(() => {
    void refresh();
    // Same name as last time, if this browser joined before.
    void wxtKV.get<Profile>(PROFILE_KEY).then((p) => {
      if (!p) return;
      setName((n) => n || p.display_name);
      setLogin((l) => l || (p.claimed_twitch_login ?? ''));
    });
  }, []);
  const codeOk = INVITE_CODE_PATTERN.test(normalizeInviteCode(code.trim()));
  const profileError = validateProfile(name.trim() || fallbackName, login);
  const canJoin = profileError === null && !busy && (!needCode || codeOk);
  const join = async (e?: FormEvent) => {
    e?.preventDefault();
    if (!canJoin) return;
    setBusy(true);
    setMsg(null);
    const params = {
      display_name: name.trim() || fallbackName,
      claimed_twitch_login: login.trim() || null,
      ...(needCode ? { invite_code: code.trim() } : {}),
    };
    const r = await askBackground<{ me: Me }>('enroll', params);
    setBusy(false);
    if (r?.ok) {
      setCode('');
      setNeedCode(false);
      await wxtKV.set<Profile>(PROFILE_KEY, { display_name: r.body.me.user.display_name, claimed_twitch_login: r.body.me.user.claimed_twitch_login });
      setMsg({ ok: true, text: `Signed in as ${r.body.me.user.display_name}.` });
    } else if (r && refusesNameOnly(r)) {
      if (needCode) setMsg({ ok: false, text: 'That invite code is invalid, used or expired.' });
      else {
        setNeedCode(true);
        setMsg({ ok: false, text: 'This server needs an invite code. Enter it, then press Join.' });
      }
    } else if (r && !r.ok && r.kind === 'http') {
      const copy = describeError(r.error.error);
      setMsg({ ok: false, text: `${copy.title}. ${copy.detail}` });
    } else setMsg({ ok: false, text: 'Could not reach the FaZeTime API. Try again.' });
    void refresh();
  };
  return (
    <main>
      <Header badge={null} />
      {st?.enrolled ? (
        <>
          <p className="ok">
            Signed in as <b>{st.displayName}</b>.
          </p>
          <p className="fine">FaZeTime appears beside chat on twitch.tv/{st.channel}.</p>
          <button type="button" onClick={() => void askBackground('signout').then(refresh)}>
            Sign out
          </button>
        </>
      ) : (
        <form onSubmit={(e) => void join(e)} noValidate>
          {st?.reenroll && <p className="err">Your session ended. Join again.</p>}
          <label>
            Your name
            <input name="display_name" value={name} maxLength={64} onChange={(e) => setName(e.target.value)} placeholder={`${fallbackName} (optional)`} />
          </label>
          <label>
            Twitch name (optional)
            <input name="twitch_login" value={login} maxLength={25} onChange={(e) => setLogin(e.target.value)} placeholder="your_twitch_name" />
            <span className="fine">Not verified. It is only a label and does not log you in.</span>
          </label>
          {needCode && (
            <label>
              Invite code
              <input name="invite_code" value={code} autoComplete="off" spellCheck={false} onChange={(e) => setCode(e.target.value)} placeholder="XXXX-XXXX-XXXX" />
            </label>
          )}
          {needCode && code !== '' && !codeOk && <p className="err">Invite codes have 12 letters or digits (dashes optional).</p>}
          {profileError && name !== '' && <p className="err">{profileError}</p>}
          <button type="submit" disabled={!canJoin}>
            {busy ? 'Joining…' : 'Join'}
          </button>
        </form>
      )}
      {msg && <p className={msg.ok ? 'ok' : 'err'}>{msg.text}</p>}
    </main>
  );
}

const rootEl = document.getElementById('root');
if (rootEl)
  createRoot(rootEl).render(
    <StrictMode>{FAZETIME_MODE === 'live' ? <LiveEnroll /> : <MockProfile />}</StrictMode>,
  );
