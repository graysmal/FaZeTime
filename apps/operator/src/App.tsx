import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { parseCapabilities, type Capabilities } from './api/capabilities';
import { OperatorClient } from './api/client';
import { clearSession, loadSession, saveSession, type StoredSession } from './api/session';
import { AiPanel } from './ui/AiPanel';
import { ErrorNotice } from './ui/common';
import { EvidencePanel } from './ui/EvidencePanel';
import { formatUtcDayTime } from './ui/format';
import { usePoll, useNow } from './ui/hooks';
import { InvitePanel } from './ui/InvitePanel';
import { MarketPanel } from './ui/MarketPanel';
import { RunPanel } from './ui/RunPanel';
import { SignIn } from './ui/SignIn';
import { StatusHeader } from './ui/StatusHeader';

function DemoLabel() {
  return <span className="demo-pill">DEMO · TEST MONEY ONLY</span>;
}

function Dashboard({ client, session, onSignOut }: { client: OperatorClient; session: StoredSession; onSignOut: () => void }) {
  const healthFn = useCallback((signal: AbortSignal) => client.health(signal), [client]);
  const health = usePoll(healthFn, 2_000);
  const streamId = health.data?.stream?.stream_id ?? null;
  // Modes as viewers see them (payment_mode is not in operator health); polled with health while a stream exists.
  const modesFn = useCallback(
    async (signal: AbortSignal) => (streamId ? (await client.snapshot(streamId, signal)).modes : null),
    [client, streamId],
  );
  const modes = usePoll(modesFn, 2_000, streamId !== null);

  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [capsError, setCapsError] = useState<unknown>(null);
  const [capsNonce, setCapsNonce] = useState(0);
  useEffect(() => {
    const ctrl = new AbortController();
    setCaps(null);
    setCapsError(null);
    client
      .openapi(ctrl.signal)
      .then((doc) => setCaps(parseCapabilities(doc)))
      .catch((e: unknown) => {
        if (!ctrl.signal.aborted) setCapsError(e);
      });
    return () => ctrl.abort();
  }, [client, capsNonce]);

  const now = useNow(500);
  const serverNowMs =
    health.data && health.okAt !== null ? Date.parse(health.data.server_time_utc) + Math.max(0, now - health.okAt) : null;
  const refresh = health.refresh;

  return (
    <div className="app">
      <header className="topbar">
        <h1>
          FaZeTime <span className="accent">Operator</span>
        </h1>
        <DemoLabel />
        <span className="spacer" />
        <span className="who" data-testid="signed-in-as">
          {session.display_name} · OPERATOR · session until {formatUtcDayTime(session.expires_at_utc)}
        </span>
        <button
          type="button"
          className="btn small"
          onClick={onSignOut}
          title="Forgets this tab's token. The server session stays valid until it expires (there is no self-logout route yet)."
        >
          Sign out
        </button>
      </header>
      <StatusHeader
        health={health.data}
        healthError={health.error}
        okAt={health.okAt}
        now={now}
        modes={streamId ? modes.data ?? null : null}
        modesError={streamId ? modes.error : null}
      />
      <div className="main-grid">
        <MarketPanel
          client={client}
          onChanged={refresh}
          health={health.data}
          serverNowMs={serverNowMs}
          settleReasonField={caps?.settleReasonField ?? null}
        />
        <div className="side">
          <InvitePanel client={client} />
          <RunPanel client={client} health={health.data} onChanged={refresh} />
        </div>
      </div>
      <div className="lower-grid">
        <EvidencePanel client={client} caps={caps} capsError={capsError} onRecheck={() => setCapsNonce((n) => n + 1)} />
        <AiPanel aiMode={health.data?.run?.ai_mode ?? null} caps={caps} />
      </div>
      <footer className="muted small">
        Demo build: test money only, no real payments, no prizes. Every operator action needs a fresh operation_id and is
        audited by the server. Times are server UTC; countdowns are approximate and the server decides every deadline.
      </footer>
    </div>
  );
}

export function App() {
  const [session, setSession] = useState<StoredSession | null>(() => loadSession());
  const [verified, setVerified] = useState(false);
  const [verifyError, setVerifyError] = useState<unknown>(null);
  const [verifyNonce, setVerifyNonce] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const tokenRef = useRef<string | null>(session?.token ?? null);

  const signOut = useCallback((message: string | null) => {
    clearSession();
    tokenRef.current = null;
    setSession(null);
    setVerified(false);
    setVerifyError(null);
    setNotice(message);
  }, []);
  const signOutRef = useRef(signOut);
  signOutRef.current = signOut;

  const client = useMemo(
    () =>
      new OperatorClient({
        getToken: () => tokenRef.current,
        onUnauthorized: () => signOutRef.current('Your session is missing, expired or revoked (401). Sign in again.'),
        onForbidden: () =>
          signOutRef.current('This session is not an operator session (403). Sign in with an operator invite.'),
      }),
    [],
  );

  // A session restored from sessionStorage is re-checked with the server before use (role must be OPERATOR).
  useEffect(() => {
    if (!session || verified) return undefined;
    const ctrl = new AbortController();
    setVerifyError(null);
    client
      .me(ctrl.signal)
      .then((me) => {
        if (me.user.role !== 'OPERATOR') signOutRef.current(`This session belongs to a ${me.user.role} account. Operator only.`);
        else setVerified(true);
      })
      .catch((e: unknown) => {
        if (!ctrl.signal.aborted) setVerifyError(e);
      });
    return () => ctrl.abort();
  }, [client, session, verified, verifyNonce]);

  if (!session) {
    return (
      <SignIn
        client={client}
        notice={notice}
        onSignedIn={(s) => {
          saveSession(s);
          tokenRef.current = s.token;
          setNotice(null);
          setSession(s);
          setVerified(true);
        }}
      />
    );
  }
  if (!verified) {
    return (
      <main className="signin">
        <div className="panel signin-card">
          <h1>
            FaZeTime <span className="accent">Operator</span>
          </h1>
          <DemoLabel />
          {verifyError ? (
            <>
              <ErrorNotice error={verifyError} title="Could not verify the saved session" />
              <div className="actions">
                <button type="button" className="btn" onClick={() => setVerifyNonce((n) => n + 1)}>
                  Retry
                </button>
                <button type="button" className="btn" onClick={() => signOut(null)}>
                  Sign out
                </button>
              </div>
            </>
          ) : (
            <p className="muted">Checking the saved session…</p>
          )}
        </div>
      </main>
    );
  }
  return <Dashboard client={client} session={session} onSignOut={() => signOut('Signed out.')} />;
}
