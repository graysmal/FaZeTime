import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { parseCapabilities, type Capabilities } from './api/capabilities';
import { OperatorClient, type ReauthOutcome } from './api/client';
import { createReopener, loadOrCreateDeviceId } from './api/openAccess';
import { clearSession, loadSession, saveSession, type StoredSession } from './api/session';
import { DemoView } from './demo/DemoView';
import { AiPanel } from './ui/AiPanel';
import { EvidencePanel } from './ui/EvidencePanel';
import { formatUtcDayTime } from './ui/format';
import { usePoll, useNow } from './ui/hooks';
import { InvitePanel } from './ui/InvitePanel';
import { MarketPanel } from './ui/MarketPanel';
import { RunPanel } from './ui/RunPanel';
import { SignIn } from './ui/SignIn';
import { StatusHeader } from './ui/StatusHeader';
import { OdysseySky, ThemeSwitch, useTheme } from './ui/theme';

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
  // Newer APIs put modes in operator health; the snapshot poll is only a fallback for older ones.
  const healthHasModes = Boolean(health.data?.modes);
  const modes = usePoll(modesFn, 2_000, streamId !== null && health.data !== null && !healthHasModes);
  const ai = health.data?.ai ?? null;
  const pending = (ai?.pending_candidates ?? 0) + (ai?.pending_resolutions ?? 0);
  useEffect(() => {
    const base = 'FaZeTime Operator (DEMO, test money only)';
    document.title = pending > 0 ? `(${pending} need action) ${base}` : base;
    return () => {
      document.title = base;
    };
  }, [pending]);

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
  const [theme, setTheme] = useTheme();

  return (
    <div className="app">
      {theme === 'enrage' && <OdysseySky />}
      <header className="topbar">
        <h1>
          Fa<span className="logo-ze">Ze</span>Time <span className="accent">Operator</span>
        </h1>
        <DemoLabel />
        {(ai?.pending_candidates ?? 0) > 0 && (
          <span className="badge alert" data-testid="attention-candidates">
            AI: {ai?.pending_candidates} candidate(s) pending
          </span>
        )}
        {(ai?.pending_resolutions ?? 0) > 0 && (
          <span className="badge alert" data-testid="attention-resolutions">
            AI: {ai?.pending_resolutions} resolution(s) to approve
          </span>
        )}
        <span className="spacer" />
        <ThemeSwitch theme={theme} onChange={setTheme} />
        <a className="btn small" href="#" data-testid="demo-view-link">
          Demo view
        </a>
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
        modes={health.data?.modes ?? (streamId ? modes.data ?? null : null)}
        modesError={healthHasModes ? null : streamId ? modes.error : null}
      />
      <div className="main-grid">
        <div className="left">
          <AiPanel
            client={client}
            ai={ai}
            markets={health.data?.markets ?? []}
            limits={health.data?.market_limits ?? null}
            hasStream={Boolean(health.data?.stream)}
            onChanged={refresh}
          />
          <MarketPanel
            client={client}
            onChanged={refresh}
            health={health.data}
            serverNowMs={serverNowMs}
            settleReasonField={caps?.settleReasonField ?? 'note'}
          />
        </div>
        <div className="side">
          <InvitePanel client={client} />
          <RunPanel client={client} health={health.data} onChanged={refresh} />
        </div>
      </div>
      <EvidencePanel client={client} caps={caps} capsError={capsError} onRecheck={() => setCapsNonce((n) => n + 1)} />
      <footer className="muted small">
        Demo build: test money only, no real payments, no prizes. Every operator action needs a fresh operation_id and is
        audited by the server. Times are server UTC; countdowns are approximate and the server decides every deadline.
      </footer>
    </div>
  );
}

type View = 'demo' | 'advanced';

function readView(): View {
  return typeof window !== 'undefined' && window.location.hash === '#advanced' ? 'advanced' : 'demo';
}

/** #advanced shows the full console; anything else shows the minimal demo view. */
function useHashView(): View {
  const [view, setView] = useState<View>(readView);
  useEffect(() => {
    const onHash = () => setView(readView());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  return view;
}

function Connecting({ trouble }: { trouble: boolean }) {
  return (
    <div className="demo" data-testid="connecting">
      <header className="demo-top">
        <h1>FaZeTime</h1>
        <span className="stream-pill connecting">Connecting…</span>
      </header>
      <main className="demo-main">
        <section className="demo-card" data-state="connecting">
          <div className="demo-wait">{trouble ? "Can't reach the server. Retrying…" : 'Connecting…'}</div>
        </section>
      </main>
    </div>
  );
}

export function App() {
  const [session, setSession] = useState<StoredSession | null>(() => loadSession());
  const [verified, setVerified] = useState(false);
  const [verifyError, setVerifyError] = useState<unknown>(null);
  const [verifyNonce, setVerifyNonce] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  // D35: false until the server answers the open-access route with 404 (invite mode). Only then is the sign-in
  // form ever shown; in open mode every lost session is replaced silently.
  const [inviteMode, setInviteMode] = useState(false);
  const [connectTrouble, setConnectTrouble] = useState(false);
  const [connectNonce, setConnectNonce] = useState(0);
  const view = useHashView();
  const tokenRef = useRef<string | null>(session?.token ?? null);

  const adopt = useCallback((s: StoredSession) => {
    saveSession(s);
    tokenRef.current = s.token;
    setNotice(null);
    setSession(s);
    setVerified(true);
    setVerifyError(null);
    setConnectTrouble(false);
  }, []);
  /** Clears only this tab's session (the device id stays). In open mode the app then opens a fresh one. */
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
  const adoptRef = useRef(adopt);
  adoptRef.current = adopt;
  const reopenRef = useRef<() => Promise<ReauthOutcome>>(async () => 'invite_mode');

  const client = useMemo(
    () =>
      new OperatorClient({
        getToken: () => tokenRef.current,
        onUnauthorized: () => signOutRef.current('Your session is missing, expired or revoked (401). Sign in again.'),
        onForbidden: () =>
          signOutRef.current('This session is not an operator session (403). Sign in with an operator invite.'),
        reauthenticate: () => reopenRef.current(),
      }),
    [],
  );
  const reopen = useMemo(
    () =>
      createReopener({
        open: (deviceId) => client.openOperatorSession(deviceId),
        deviceId: () => loadOrCreateDeviceId(),
        onSession: (s) => adoptRef.current(s),
        onInviteMode: () => setInviteMode(true),
      }),
    [client],
  );
  reopenRef.current = reopen;

  // No session: open one silently (D35). 404 switches to invite mode; anything else retries after a pause.
  useEffect(() => {
    if (session || inviteMode) return undefined;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    void reopen().then((outcome) => {
      if (cancelled || outcome !== 'failed') return;
      setConnectTrouble(true);
      timer = setTimeout(() => setConnectNonce((n) => n + 1), Math.max(1_000, reopen.retryInMs() + 50));
    });
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [session, inviteMode, reopen, connectNonce]);

  // A session restored from sessionStorage is re-checked with the server before use (role must be OPERATOR).
  // A 401 here is handled by the client (silent re-open in open mode); other failures retry after a pause.
  useEffect(() => {
    if (!session || verified) return undefined;
    const ctrl = new AbortController();
    let timer: ReturnType<typeof setTimeout> | null = null;
    setVerifyError(null);
    client
      .me(ctrl.signal)
      .then((me) => {
        if (me.user.role !== 'OPERATOR') signOutRef.current(`This session belongs to a ${me.user.role} account. Operator only.`);
        else setVerified(true);
      })
      .catch((e: unknown) => {
        if (ctrl.signal.aborted) return;
        setVerifyError(e);
        timer = setTimeout(() => setVerifyNonce((n) => n + 1), 3_000);
      });
    return () => {
      ctrl.abort();
      if (timer) clearTimeout(timer);
    };
  }, [client, session, verified, verifyNonce]);

  if (!session) {
    if (inviteMode) return <SignIn client={client} notice={notice} onSignedIn={adopt} />;
    return <Connecting trouble={connectTrouble} />;
  }
  if (!verified) return <Connecting trouble={verifyError !== null} />;
  if (view === 'advanced') return <Dashboard client={client} session={session} onSignOut={() => signOut('Signed out.')} />;
  return <DemoView client={client} />;
}
