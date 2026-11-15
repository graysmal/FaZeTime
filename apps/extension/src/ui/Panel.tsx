import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import type { ErrorCode, Modes } from '@fazetime/contracts';
import { checkTopUp, describeAmountProblem, formatMinor, parseDollarsToMinor } from '../lib/money';
import type { PanelNotice, Placement } from '../content/mount';
import { MarketCard } from './MarketCard';
import { PANEL_OPEN_KEY, PROFILE_KEY, panelHeightKey, useEnv, usePanel, useStoredValue, type Profile } from './hooks';

export const PANEL_MIN_PX = 160;
export const CHAT_MIN_PX = 140;
export const PANEL_DEFAULT_PX = 360;
const KEY_STEP_PX = 16;
const PAGE_STEP_PX = 80;

/** Clamp the panel height so chat keeps at least CHAT_MIN_PX. */
export function clampPanelHeight(px: number, containerPx: number): number {
  const max = Math.max(PANEL_MIN_PX, containerPx - CHAT_MIN_PX);
  return Math.round(Math.min(max, Math.max(PANEL_MIN_PX, px)));
}

/** MOCK badge for local fixture builds only. Live builds show no badge (D31). */
export function ModeBadge() {
  const { mode } = useEnv();
  if (mode === 'live') return null;
  return (
    <span className="ft-badge ft-badge--mock" title="Local mock data. No backend, no real money.">
      MOCK
    </span>
  );
}

/** The single, unobtrusive honesty note for live builds (D31). */
export const TEST_CREDITS_NOTE = 'Balances are test credits.';

export function ModeChips({ modes, adapter }: { modes: Modes | undefined; adapter: string | null }) {
  const { mode } = useEnv();
  if (mode === 'live') return null; // D31: the operator console carries mode labels.
  const media = modes?.media_source_kind ?? 'NONE';
  return (
    <div className="ft-modes" aria-label="Demo mode labels">
      <span className="ft-mode">
        Media: <b>{media.replace(/_/g, ' ')}</b>
      </span>
      <span className="ft-mode">
        Model: <b>{modes?.ai_mode ?? 'UNKNOWN'}</b>
      </span>
      <span className="ft-mode">
        Funds: <b>{modes?.payment_mode ?? 'UNKNOWN'}</b>
      </span>
      <span className="ft-mode">
        Data: <b>{adapter === 'LIVE' ? 'LIVE API' : 'LOCAL MOCK'}</b>
      </span>
    </div>
  );
}

type Tab = 'market' | 'wallet' | 'redeem';

export function Panel(props: { host: HTMLElement; placement: Placement; notice: PanelNotice; retryAttach: () => void }) {
  const { host, placement, notice, retryAttach } = props;
  const env = useEnv();
  const st = usePanel();
  const [open, setOpen] = useStoredValue<boolean>(PANEL_OPEN_KEY, true);
  const [height, setHeight, heightLoaded] = useStoredValue<number>(panelHeightKey(env.channel), PANEL_DEFAULT_PX);
  const [tab, setTab] = useState<Tab>('market');
  const [menuOpen, setMenuOpen] = useState(false);

  // Expand when something (e.g. the over-video dropdown) needs the panel's top-up dialog.
  useEffect(() => env.onPanelOpenRequest(() => setOpen(true)), [env]);
  useEffect(() => {
    if (st.topUp.open && !open) setOpen(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [st.topUp.open]);

  // The host lives in Twitch's flex column; its height is the panel/chat split.
  useLayoutEffect(() => {
    if (placement !== 'chat') {
      host.style.height = '';
      return;
    }
    if (!open) {
      host.style.height = 'auto';
      return;
    }
    const container = host.parentElement?.getBoundingClientRect().height ?? 0;
    host.style.height = `${container > 0 ? clampPanelHeight(height, container) : height}px`;
  }, [host, placement, open, height, heightLoaded]);

  const snap = st.snapshot;
  return (
    <div className="ft-panel" data-placement={placement}>
      <header className="ft-head">
        <div className="ft-brand">
          <span className="ft-word">
            FaZe<b>Time</b>
          </span>
          <ModeBadge />
          {snap?.market?.state === 'OPEN' && !open && <span className="ft-badge ft-badge--soft">Market open</span>}
        </div>
        <div className="ft-head-actions">
          {st.hasFixtures && open && (
            <button type="button" className="ft-chip-btn" aria-haspopup="menu" aria-expanded={menuOpen} onClick={() => setMenuOpen((v) => !v)}>
              Fixture ▾
            </button>
          )}
          <button
            type="button"
            className="ft-icon-btn"
            aria-expanded={open}
            aria-label={open ? 'Close the FaZeTime panel' : 'Open the FaZeTime panel'}
            onClick={() => setOpen(!open)}
          >
            {open ? 'Close ▴' : 'Open ▾'}
          </button>
        </div>
      </header>
      {open && (
        <>
          <ModeChips modes={snap?.modes} adapter={st.adapterMode} />
          {notice === 'chat_not_found' && (
            <div className="ft-notice ft-notice--warn">
              <span>Twitch chat was not found, so FaZeTime is floating here.</span>
              <button type="button" className="ft-link" onClick={retryAttach}>
                Retry
              </button>
            </div>
          )}
          {notice === 'reattach_paused' && (
            <div className="ft-notice ft-notice--warn">
              <span>FaZeTime stopped re-attaching to chat so it does not disrupt the page.</span>
              <button type="button" className="ft-link" onClick={retryAttach}>
                Retry
              </button>
            </div>
          )}
          {st.connection === 'disconnected' && <div className="ft-notice">Reconnecting to the extension…</div>}
          {st.backend?.mode === 'LIVE' && !st.backend.enrolled && (
            <div className="ft-notice ft-notice--warn">
              {st.backend.reenroll
                ? 'Your session ended. Open the FaZeTime toolbar popup and enroll again with a new invite code.'
                : 'Sign in: open the FaZeTime toolbar popup and enter your invite code.'}
            </div>
          )}
          {st.backend?.mode === 'LIVE' && st.backend.enrolled && (st.backend.link === 'POLLING' || st.backend.link === 'ORIGIN_REJECTED') && (
            <div className="ft-notice">{st.backend.message ?? 'Live updates reconnecting; showing polled state.'}</div>
          )}
          {st.snapshotIssue && st.snapshot && <div className="ft-notice">{st.snapshotIssue}</div>}
          {st.runNotice && (
            <div className="ft-notice">
              <span>{st.runNotice}</span>
              <button type="button" className="ft-link" onClick={() => env.controller.dismissRunNotice()}>
                OK
              </button>
            </div>
          )}
          <nav className="ft-tabs" role="tablist" aria-label="FaZeTime sections">
            {(['market', 'wallet', 'redeem'] as const).map((t) => (
              <button key={t} type="button" role="tab" aria-selected={tab === t} className="ft-tab" onClick={() => setTab(t)}>
                {t === 'market' ? 'Market' : t === 'wallet' ? 'Wallet' : 'Redeem'}
              </button>
            ))}
          </nav>
          <div className="ft-body" role="tabpanel">
            {tab === 'market' && <MarketCard surface="panel" />}
            {tab === 'wallet' && <WalletTab />}
            {tab === 'redeem' && <RedeemTab />}
          </div>
          {placement === 'chat' && <ResizeHandle host={host} height={height} onChange={setHeight} />}
        </>
      )}
      {open && st.topUp.open && <TopUpDialog />}
      {open && menuOpen && st.hasFixtures && <FixtureMenu onClose={() => setMenuOpen(false)} />}
    </div>
  );
}

function ResizeHandle({ host, height, onChange }: { host: HTMLElement; height: number; onChange: (px: number) => void }) {
  const drag = useRef<{ startY: number; startH: number; pointerId: number } | null>(null);
  const [live, setLive] = useState<number | null>(null);
  const container = () => host.parentElement?.getBoundingClientRect().height ?? 0;
  const current = live ?? height;
  const max = Math.max(PANEL_MIN_PX, container() - CHAT_MIN_PX);

  useEffect(() => {
    if (live !== null) host.style.height = `${live}px`;
  }, [live, host]);

  const commit = (px: number) => onChange(clampPanelHeight(px, container()));
  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    drag.current = { startY: e.clientY, startH: host.getBoundingClientRect().height, pointerId: e.pointerId };
    e.currentTarget.setPointerCapture(e.pointerId);
    e.preventDefault();
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d) return;
    setLive(clampPanelHeight(d.startH + (e.clientY - d.startY), container()));
  };
  const end = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d) return;
    drag.current = null;
    if (e.currentTarget.hasPointerCapture(d.pointerId)) e.currentTarget.releasePointerCapture(d.pointerId);
    if (live !== null) commit(live);
    setLive(null);
  };
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const steps: Record<string, number> = { ArrowUp: -KEY_STEP_PX, ArrowDown: KEY_STEP_PX, PageUp: -PAGE_STEP_PX, PageDown: PAGE_STEP_PX };
    const step = steps[e.key];
    if (step !== undefined) commit(height + step);
    else if (e.key === 'Home') commit(PANEL_MIN_PX);
    else if (e.key === 'End') commit(max);
    else return; // Tab and everything else keep their default behaviour: focus is never trapped.
    e.preventDefault();
  };
  return (
    <div
      className="ft-resize"
      role="separator"
      aria-orientation="horizontal"
      aria-label="Resize the FaZeTime panel and chat"
      aria-valuemin={PANEL_MIN_PX}
      aria-valuemax={Math.round(max)}
      aria-valuenow={Math.round(current)}
      tabIndex={0}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={end}
      onPointerCancel={end}
      onKeyDown={onKeyDown}
    />
  );
}

export function WalletTab() {
  const { controller, mode } = useEnv();
  const st = usePanel();
  const [profile] = useStoredValue<Profile | null>(PROFILE_KEY, null);
  const w = st.snapshot?.wallet;
  return (
    <div>
      <div className="ft-wallet-grid">
        <div className="ft-stat">
          <span>Available</span>
          <b>{w ? formatMinor(w.available_minor) : '…'}</b>
        </div>
        <div className="ft-stat">
          <span>In play</span>
          <b>{w ? formatMinor(w.in_play_minor) : '…'}</b>
        </div>
      </div>
      {st.snapshot?.modes.payment_mode === 'MOCK' ? (
        <button type="button" className="ft-primary" onClick={() => controller.openTopUp('manual')}>
          {mode === 'live' ? 'Add funds' : 'Add demo funds (MOCK)'}
        </button>
      ) : (
        <button type="button" className="ft-primary" disabled>
          Top-ups aren't available yet
        </button>
      )}
      <p className="ft-fine">{mode === 'live' ? TEST_CREDITS_NOTE : 'Demo funds only. Not money, cannot be withdrawn, and only valid in this demo run.'}</p>
      <div className="ft-stat">
        <span>Profile (set in the FaZeTime toolbar popup)</span>
        <b style={{ fontSize: 14 }}>{profile?.display_name || 'No display name yet'}</b>
        {profile?.claimed_twitch_login && (
          <span>
            Claimed Twitch login: {profile.claimed_twitch_login} <em>(not verified)</em>
          </span>
        )}
      </div>
    </div>
  );
}

function RedeemTab() {
  const { controller, mode } = useEnv();
  const st = usePanel();
  useEffect(() => {
    if (!st.catalog) void controller.loadCatalog();
  }, [controller, st.catalog]);
  const { busyItem, receipt, error } = st.redeem;
  const unavailable = st.snapshot !== null && st.snapshot.modes.payment_mode !== 'MOCK';
  return (
    <div>
      {mode === 'live' && unavailable ? (
        <p className="ft-fine">Rewards aren't available yet.</p>
      ) : (
        <p className="ft-fine">Tiny fixed demo catalog. Codes are random and NON-REDEEMABLE: no store, coupon or prize exists.</p>
      )}
      {(st.catalog ?? []).map((item) => (
        <div className="ft-item" key={item.item_id}>
          <div>
            <strong>{item.title}</strong>
            <p>{item.description}</p>
          </div>
          <button type="button" className="ft-secondary" disabled={busyItem !== null || unavailable} onClick={() => void controller.redeem(item.item_id)}>
            {unavailable ? 'Not available yet' : busyItem === item.item_id ? 'Redeeming…' : `Redeem ${formatMinor(item.price_minor)}`}
          </button>
        </div>
      ))}
      {error && (
        <p className="ft-field-error" role="alert">
          {error}
        </p>
      )}
      {receipt && (
        <div className="ft-code" role="status">
          <span className="ft-badge ft-badge--mock">NON-REDEEMABLE DEMO CODE</span>
          <code>{receipt.demo_code}</code>
          <span className="ft-fine">
            Debited {formatMinor(receipt.price_minor)} of demo funds{receipt.replayed ? ' (same request replayed; charged once)' : ''}. Not valid anywhere.
          </span>
        </div>
      )}
    </div>
  );
}

export function TopUpDialog() {
  const { controller, mode } = useEnv();
  const st = usePanel();
  const limits = st.snapshot?.limits;
  const t = st.topUp;
  const [choice, setChoice] = useState<number | 'custom'>(() => limits?.topup_presets_minor[0] ?? 0);
  const [customText, setCustomText] = useState('');
  const firstRef = useRef<HTMLButtonElement>(null);
  useEffect(() => firstRef.current?.focus(), []);
  if (!limits) return null;
  if (st.snapshot?.modes.payment_mode !== 'MOCK') {
    return (
      <div className="ft-backdrop" onKeyDown={(e) => e.key === 'Escape' && controller.closeTopUp()}>
        <div className="ft-dialog" role="dialog" aria-modal="false" aria-labelledby="ft-topup-title">
          <div className="ft-row">
            <h4 id="ft-topup-title">Add funds</h4>
          </div>
          {t.reason === 'insufficient' && t.neededMinor ? (
            <p className="ft-hint ft-hint--warn">You need {formatMinor(t.neededMinor)} more for that bet.</p>
          ) : null}
          <p className="ft-hint">Top-ups aren't available yet. Nothing can be charged.</p>
          <p className="ft-fine">{mode === 'live' ? TEST_CREDITS_NOTE : 'Stripe test-mode top-ups arrive in phase 6.'}</p>
          <button ref={firstRef} type="button" className="ft-secondary" onClick={() => controller.closeTopUp()}>
            Close
          </button>
        </div>
      </div>
    );
  }
  const amount = choice === 'custom' ? parseDollarsToMinor(customText) : choice;
  const problem = checkTopUp(amount, limits);
  const busy = t.status === 'submitting';
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      controller.closeTopUp();
    }
  };
  return (
    <div className="ft-backdrop" onKeyDown={onKey}>
      <div className="ft-dialog" role="dialog" aria-modal="false" aria-labelledby="ft-topup-title">
        <div className="ft-row">
          <h4 id="ft-topup-title">Add demo funds</h4>
          <span className="ft-badge ft-badge--mock">MOCK · no payment</span>
        </div>
        <p className="ft-fine">
          Synthetic test top-up: no card, no charge, no real money. A Stripe test-mode checkout replaces this in a later phase.
        </p>
        {t.reason === 'insufficient' && (
          <p className="ft-hint ft-hint--warn">
            {t.neededMinor ? `You need ${formatMinor(t.neededMinor)} more for that bet. ` : ''}Topping up does not hold your bet or the market;
            it may close before you are back.
          </p>
        )}
        <div className="ft-amounts" role="group" aria-label="Top-up amount">
          {limits.topup_presets_minor.map((p, i) => (
            <button
              key={p}
              ref={i === 0 ? firstRef : undefined}
              type="button"
              className="ft-amount"
              aria-pressed={choice === p}
              disabled={busy}
              onClick={() => setChoice(p)}
            >
              {formatMinor(p).replace('.00', '')}
            </button>
          ))}
          <button type="button" className="ft-amount" aria-pressed={choice === 'custom'} disabled={busy} onClick={() => setChoice('custom')}>
            Custom
          </button>
        </div>
        {choice === 'custom' && (
          <label className="ft-label">
            Custom amount ({formatMinor(limits.topup_min_minor)} to {formatMinor(limits.topup_max_minor)}, steps of {formatMinor(limits.topup_step_minor)})
            <input className="ft-input" inputMode="decimal" value={customText} placeholder="20" onChange={(e) => setCustomText(e.target.value)} />
          </label>
        )}
        {problem && choice === 'custom' && customText !== '' && (
          <div className="ft-field-error">{describeAmountProblem(problem, limits.topup_min_minor, limits.topup_max_minor, limits.topup_step_minor)}</div>
        )}
        <button type="button" className="ft-primary" disabled={busy || problem !== null || amount === null} onClick={() => amount !== null && void controller.submitTopUp(amount)}>
          {busy ? 'Adding…' : 'FaZe Up!'}
        </button>
        {t.message && (
          <div className={`ft-status ${t.status === 'credited' ? 'ft-status--ok' : t.status === 'error' ? 'ft-status--err' : 'ft-status--wait'}`} role="status">
            {t.message}
          </div>
        )}
        <button type="button" className="ft-secondary" onClick={() => controller.closeTopUp()} disabled={busy}>
          {t.status === 'credited' ? 'Done' : 'Cancel'}
        </button>
      </div>
    </div>
  );
}

function FixtureMenu({ onClose }: { onClose: () => void }) {
  const { controller } = useEnv();
  const { fixtureInfo } = usePanel();
  useEffect(() => {
    void controller.refreshFixtureInfo();
  }, [controller]);
  if (!fixtureInfo) return null;
  return (
    <div className="ft-menu" role="menu" aria-label="Fixture (dev)" onKeyDown={(e) => e.key === 'Escape' && onClose()}>
      <h5>Fixture (dev · MOCK only)</h5>
      {fixtureInfo.names.map((name) => (
        <button
          key={name}
          type="button"
          role="menuitemradio"
          aria-checked={fixtureInfo.current === name}
          className="ft-menu-item"
          onClick={() => {
            void controller.loadFixture(name);
            onClose();
          }}
        >
          {fixtureInfo.current === name ? '● ' : '○ '}
          {name}
        </button>
      ))}
      <hr className="ft-menu-sep" />
      <label className="ft-label">
        Next bet/top-up fails with
        <select
          className="ft-select"
          value={fixtureInfo.injectedError ?? ''}
          onChange={(e) => void controller.injectError((e.target.value || null) as ErrorCode | null)}
        >
          <option value="">(no injected error)</option>
          {fixtureInfo.errorCodes.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </label>
      <button type="button" role="menuitem" className="ft-menu-item" onClick={() => void controller.armTimeout()}>
        {fixtureInfo.timeoutArmed ? '● Timeout armed for next bet' : '○ Simulate timeout on next bet'}
      </button>
      <button type="button" role="menuitem" className="ft-menu-item" onClick={() => void controller.loadFixture(fixtureInfo.current).then(onClose)}>
        ↻ Restart clock on {fixtureInfo.current}
      </button>
    </div>
  );
}
