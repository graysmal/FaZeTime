// Popup.
// - mock builds (P1-B): display name + optional claimed Twitch login, stored locally.
// - live builds (P2): invite code + display name + optional Twitch login are sent to the BACKGROUND,
//   which calls POST /v1/enroll and keeps the session token. The popup never receives the token.
// The Twitch login is a label, NOT verified identity. No phone field (D16), no card fields, ever.
import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { browser } from 'wxt/browser';
import { CLAIMED_TWITCH_LOGIN_PATTERN, INVITE_CODE_PATTERN, normalizeInviteCode, type Me } from '@fazetime/contracts';
import type { ApiResult, BackgroundStatus } from '../../src/api/types';
import { FAZETIME_MODE } from '../../src/config';
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

const ask = <T,>(method: 'status' | 'enroll' | 'signout', params?: unknown) =>
  browser.runtime.sendMessage({ t: 'popup', method, params }) as Promise<ApiResult<T>>;

function Header({ badge }: { badge: string }) {
  return (
    <header>
      <h1>
        FaZe<b>Time</b>
      </h1>
      <span className="mock">{badge}</span>
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

function LiveEnroll() {
  const [st, setSt] = useState<BackgroundStatus | null>(null);
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [login, setLogin] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const refresh = () => ask<BackgroundStatus>('status').then((r) => r?.ok && setSt(r.body));
  useEffect(() => {
    void refresh();
  }, []);
  const codeOk = INVITE_CODE_PATTERN.test(normalizeInviteCode(code.trim()));
  const profileError = validateProfile(name, login);
  const enroll = async () => {
    if (!codeOk || profileError || busy) return;
    setBusy(true);
    setMsg(null);
    const r = await ask<{ me: Me }>('enroll', { invite_code: code.trim(), display_name: name.trim(), claimed_twitch_login: login.trim() || null });
    setBusy(false);
    if (r?.ok) {
      setCode('');
      await wxtKV.set<Profile>(PROFILE_KEY, { display_name: r.body.me.user.display_name, claimed_twitch_login: r.body.me.user.claimed_twitch_login });
      setMsg({ ok: true, text: `Enrolled as ${r.body.me.user.display_name}.` });
    } else if (r && !r.ok && r.kind === 'http') {
      const text =
        r.error.error.code === 'UNAUTHENTICATED' ? 'That invite code is invalid, used or expired.' : `${describeError(r.error.error).title}. ${describeError(r.error.error).detail}`;
      setMsg({ ok: false, text });
    } else setMsg({ ok: false, text: 'Could not reach the FaZeTime API. Try again.' });
    void refresh();
  };
  return (
    <main>
      <Header badge="DEMO · TEST MONEY" />
      <p className="fine">Live demo API at {st?.apiBase ?? '…'}. Test money only; nothing here is real money.</p>
      {st?.enrolled ? (
        <>
          <p className="ok">
            Enrolled as <b>{st.displayName}</b> ({st.role?.toLowerCase()}). Updates: {st.link.toLowerCase()}.
          </p>
          <p className="fine">The panel appears on twitch.tv/{st.channel}.</p>
          <button type="button" onClick={() => void ask('signout').then(refresh)}>
            Sign out on this browser
          </button>
        </>
      ) : (
        <>
          {st?.reenroll && <p className="err">Your session ended. Enroll again with a new invite code.</p>}
          <label>
            Invite code
            <input value={code} autoComplete="off" spellCheck={false} onChange={(e) => setCode(e.target.value)} placeholder="XXXX-XXXX-XXXX" />
          </label>
          <label>
            Display name
            <input value={name} maxLength={64} onChange={(e) => setName(e.target.value)} placeholder="PixelPilot" />
          </label>
          <label>
            Twitch login (optional)
            <input value={login} maxLength={25} onChange={(e) => setLogin(e.target.value)} placeholder="your_twitch_name" />
            <span className="fine">Not verified. It is only a label and does not log you in.</span>
          </label>
          {code !== '' && !codeOk && <p className="err">Invite codes have 12 letters or digits (dashes optional).</p>}
          {profileError && name !== '' && <p className="err">{profileError}</p>}
          <button type="button" disabled={!codeOk || profileError !== null || busy} onClick={() => void enroll()}>
            {busy ? 'Enrolling…' : 'Enroll'}
          </button>
        </>
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
