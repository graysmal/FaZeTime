import { useState, type FormEvent } from 'react';
import { ApiFailure, type OperatorClient } from '../api/client';
import type { StoredSession } from '../api/session';
import { ErrorNotice } from './common';
import { INVITE_RE, normalizeInvite } from './format';

export function SignIn({
  client,
  notice,
  onSignedIn,
}: {
  client: OperatorClient;
  notice: string | null;
  onSignedIn: (session: StoredSession) => void;
}) {
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const [refusal, setRefusal] = useState<string | null>(null);

  const normalized = normalizeInvite(code);
  const trimmed = name.trim();
  const codeOk = INVITE_RE.test(normalized);
  const nameOk = trimmed.length >= 1 && trimmed.length <= 32;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!codeOk || !nameOk || busy) return;
    setBusy(true);
    setFailure(null);
    setRefusal(null);
    try {
      const res = await client.enroll({
        invite_code: normalized,
        display_name: trimmed,
        device_id: globalThis.crypto.randomUUID(),
      });
      const role = res?.me?.user?.role;
      if (role !== 'OPERATOR') {
        // The token is dropped here, never stored: this page accepts OPERATOR sessions only.
        setRefusal(
          `That invite enrolled a ${String(role ?? 'non-operator')} account, so this page will not use it. ` +
            'The operator view needs an OPERATOR invite (bootstrap-operator on the API host, or from another operator). ' +
            'The invite you entered is now used up.',
        );
        return;
      }
      setCode('');
      onSignedIn({
        token: res.session_token,
        session_id: res.session_id,
        expires_at_utc: res.expires_at_utc,
        user_id: res.me.user.user_id,
        display_name: res.me.user.display_name,
      });
    } catch (err) {
      setFailure(err);
    } finally {
      setBusy(false);
    }
  }

  const unauth = failure instanceof ApiFailure && failure.status === 401;
  return (
    <main className="signin">
      <form className="panel signin-card" onSubmit={submit} method="post" autoComplete="off" noValidate>
        <h1>
          FaZeTime <span className="accent">Operator</span>
        </h1>
        <p className="demo-label">DEMO · TEST MONEY ONLY · no real payments</p>
        {notice && (
          <div className="notice unknown" role="status">
            {notice}
          </div>
        )}
        <label>
          Operator invite code
          <input
            name="invite_code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="XXXX-XXXX-XXXX"
            spellCheck={false}
            autoCapitalize="characters"
            maxLength={20}
            aria-invalid={code !== '' && !codeOk}
          />
        </label>
        {code !== '' && !codeOk && <div className="muted small">12 characters (Crockford base32; hyphens optional).</div>}
        <label>
          Display name
          <input name="display_name" value={name} onChange={(e) => setName(e.target.value)} maxLength={32} />
        </label>
        <button type="submit" className="btn primary" disabled={!codeOk || !nameOk || busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
        {refusal && (
          <div className="notice error" role="alert">
            {refusal}
          </div>
        )}
        {unauth ? (
          <div className="notice error" role="alert">
            That code is invalid, already used, or expired. (The server does not say which.)
          </div>
        ) : (
          failure !== null && <ErrorNotice error={failure} title="Sign-in failed" />
        )}
        <p className="muted small">
          The session token stays in this tab's sessionStorage only. It is sent only as an Authorization header to this
          API, never in a URL.
        </p>
      </form>
    </main>
  );
}
