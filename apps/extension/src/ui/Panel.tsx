import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import type { ErrorCode, Modes } from '@fazetime/contracts';
import { checkTopUp, currencySymbol, describeAmountProblem, formatMinor, parseDollarsToMinor, setDisplayCurrency } from '../lib/money';
import type { PanelNotice, Placement } from '../content/mount';
import { describeTopUp } from '../state/topupCopy';
import type { RedeemItem } from '../api/types';
import { MarketCard } from './MarketCard';
import { glazeFromEvent, glazeOnHover, THEME_KEY, themeAttr, type ThemeName } from './theme';
import { OdysseySky, ThemeSwitch } from './ThemeSwitch';
import { Amphora, Laurel, setOracleFlavour } from './OdysseyDecor';
import { PANEL_OPEN_KEY, PROFILE_KEY, panelHeightKey, useEnv, usePanel, useStoredValue, type Profile } from './hooks';

export const PANEL_MIN_PX = 160;
export const CHAT_MIN_PX = 140;
export const PANEL_DEFAULT_PX = 360;
const KEY_STEP_PX = 16;
/** Collapse/expand animation length; the body stays mounted this long after closing so it can slide away. */
export const COLLAPSE_MS = 260;
/** Twitch's "Collapse Chat" button, pinned to the top-left of the chat column (verified 2026-11-15). */
const TWITCH_COLLAPSE_SELECTOR = '[data-a-target="right-column__toggle-collapse-btn"]';
const LOGO_GAP_PX = 14;

/**
 * Left inset for the panel header so the logo starts beside Twitch's Collapse Chat button instead of under
 * it. Measured (not hard-coded) because Twitch's layout varies; re-measured on resize and every 2 s.
 */
function useHeaderInset(doc: Document, host: HTMLElement, enabled: boolean): number | null {
  const [inset, setInset] = useState<number | null>(null);
  useEffect(() => {
    if (!enabled) return;
    const measure = () => {
      const btn = doc.querySelector(TWITCH_COLLAPSE_SELECTOR);
      const h = host.getBoundingClientRect();
      const r = btn?.getBoundingClientRect();
      const overlaps = r && r.width > 0 && r.bottom > h.top && r.top < h.top + 48 && r.right > h.left && r.left < h.right;
      const next = overlaps ? Math.ceil(r.right - h.left + LOGO_GAP_PX) : null;
      setInset((prev) => (prev === next ? prev : next));
    };
    measure();
    const view = doc.defaultView;
    view?.addEventListener('resize', measure);
    const timer = setInterval(measure, 2000);
    return () => {
      view?.removeEventListener('resize', measure);
      clearInterval(timer);
    };
  }, [doc, host, enabled]);
  return inset;
}
const TABS = ['market', 'wallet', 'redeem'] as const;
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
  // Direction of the last tab change, for the slide-in animation (+1 = moving right, -1 = moving left).
  const [tabDir, setTabDir] = useState<1 | -1>(1);
  const [menuOpen, setMenuOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [theme, setTheme] = useStoredValue<ThemeName>(THEME_KEY, 'calm');
  setDisplayCurrency(theme === 'enrage' ? 'DRACHMA' : 'USD'); // before children render
  setOracleFlavour(theme === 'enrage');
  const headRef = useRef<HTMLElement>(null);
  // While collapsing, keep the body rendered so the height animation has something to hide.
  const [closing, setClosing] = useState(false);
  const toggleOpen = () => {
    if (open) {
      setClosing(true);
      setTimeout(() => setClosing(false), COLLAPSE_MS);
    }
    setOpen(!open);
  };
  const selectTab = (t: Tab) => {
    if (t === tab) return;
    setTabDir(TABS.indexOf(t) > TABS.indexOf(tab) ? 1 : -1);
    setTab(t);
  };

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
    host.style.transition = `height ${COLLAPSE_MS}ms cubic-bezier(0.2, 0.8, 0.2, 1)`;
    host.style.overflow = 'hidden';
    if (!open) {
      // Collapse to the header bar (an explicit height so the change animates).
      const head = headRef.current?.getBoundingClientRect().height ?? 0;
      host.style.height = head > 0 ? `${Math.ceil(head)}px` : 'auto';
      return;
    }
    const container = host.parentElement?.getBoundingClientRect().height ?? 0;
    host.style.height = `${container > 0 ? clampPanelHeight(height, container) : height}px`;
  }, [host, placement, open, height, heightLoaded]);

  const snap = st.snapshot;
  const showBody = open || closing;
  const headInset = useHeaderInset(env.doc, host, placement === 'chat');
  return (
    <div
      className="ft-panel"
      data-placement={placement}
      data-open={open}
      data-theme={themeAttr(theme)}
      onClickCapture={(e) => glazeFromEvent(e.target)}
      onPointerOver={(e) => glazeOnHover(e)}
    >
      {theme === 'enrage' && <OdysseySky />}
      <header className="ft-head" ref={headRef} style={headInset !== null ? { paddingLeft: headInset } : undefined}>
        <div className="ft-brand">
          <span className="ft-word">
            Fa<b>Ze</b>Time
          </span>
          <ModeBadge />
          {snap?.market?.state === 'OPEN' && !open && <span className="ft-badge ft-badge--soft">Market open</span>}
        </div>
        <div className="ft-head-actions">
          <ThemeSwitch theme={theme} onChange={setTheme} />
          {open && (
            <button
              type="button"
              className="ft-icon-btn ft-profile-btn"
              aria-haspopup="dialog"
              aria-expanded={profileOpen}
              aria-label="Your FaZeTime profile"
              title="Profile"
              onClick={() => setProfileOpen((v) => !v)}
            >
              <PersonIcon />
            </button>
          )}
          {st.hasFixtures && open && (
            <button type="button" className="ft-chip-btn" aria-haspopup="menu" aria-expanded={menuOpen} onClick={() => setMenuOpen((v) => !v)}>
              Fixture ▾
            </button>
          )}
          <button
            type="button"
            className="ft-icon-btn ft-collapse"
            aria-expanded={open}
            aria-label={open ? 'Close the FaZeTime panel' : 'Open the FaZeTime panel'}
            title={open ? 'Collapse' : 'Expand'}
            onClick={toggleOpen}
          >
            {/* "−" when open, "+" when collapsed: the vertical bar folds away. */}
            <svg className="ft-toggle-icon" viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
              <rect className="ft-toggle-h" x="1" y="5" width="10" height="2" />
              <rect className="ft-toggle-v" x="5" y="1" width="2" height="10" />
            </svg>
          </button>
        </div>
      </header>
      {showBody && (
        <div className="ft-collapsible" data-state={open ? 'open' : 'closing'}>
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
                ? 'Your session ended. Open the FaZeTime toolbar popup and press Join.'
                : 'Open the FaZeTime toolbar popup and press Join.'}
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
          {st.pendingTopUp && !st.topUp.open && <TopUpNotice />}
          <nav className="ft-tabs" role="tablist" aria-label="FaZeTime sections" style={{ ['--ft-tab-i' as string]: TABS.indexOf(tab) }}>
            {TABS.map((t) => (
              <button key={t} type="button" role="tab" aria-selected={tab === t} className="ft-tab" onClick={() => selectTab(t)}>
                {theme === 'enrage'
                  ? t === 'market'
                    ? 'Agora'
                    : t === 'wallet'
                      ? 'Treasury'
                      : 'Voyage'
                  : t === 'market'
                    ? 'Market'
                    : t === 'wallet'
                      ? 'Wallet'
                      : 'Redeem'}
              </button>
            ))}
            <span className="ft-tab-ink" aria-hidden="true" />
          </nav>
          <div className="ft-body" role="tabpanel">
            <div key={tab} className="ft-pane" data-tab={tab} data-dir={tabDir > 0 ? 'right' : 'left'}>
              {tab === 'market' && <MarketCard surface="panel" />}
              {tab === 'wallet' && <WalletTab />}
              {tab === 'redeem' && <RedeemTab />}
            </div>
          </div>
          {placement === 'chat' && open && <ResizeHandle host={host} height={height} onChange={setHeight} />}
        </div>
      )}
      {open && st.topUp.open && <TopUpDialog />}
      {open && menuOpen && st.hasFixtures && <FixtureMenu onClose={() => setMenuOpen(false)} />}
      {open && profileOpen && (
        <ProfileCard
          top={(headRef.current?.getBoundingClientRect().height ?? 40) + 8}
          onClose={() => setProfileOpen(false)}
          onAddFunds={() => {
            setProfileOpen(false);
            selectTab('wallet');
          }}
        />
      )}
    </div>
  );
}

function PersonIcon() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" fill="currentColor">
      <circle cx="8" cy="5" r="3" />
      <path d="M2 15c0-3.3 2.7-5.5 6-5.5s6 2.2 6 5.5z" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
      <path d="M2 6.5l2.5 2.5L10 3.5" fill="none" stroke="currentColor" strokeWidth="2" />
    </svg>
  );
}

/** Up to two initials from a display name ("Faze Gavin" -> "FG", "gavin" -> "GA"); "?" when unknown. */
export function initialsFor(name: string | null | undefined): string {
  const words = (name ?? '')
    .trim()
    .split(/[\s_.-]+/)
    .filter(Boolean);
  if (words.length === 0) return '?';
  const letters = words.length >= 2 ? words[0]![0]! + words[1]![0]! : [...words[0]!].slice(0, 2).join('');
  return letters.toUpperCase();
}

export const VERIFY_NOTE = 'You need to verify before you can bet. Verifying means joining this stream from the FaZeTime popup.';
export const VERIFY_FALLBACK = 'Click the FaZeTime icon in your browser toolbar, then press Join.';

/**
 * Profile card (owner requests, 2026-11-15): initials avatar, name, claimed Twitch name, available balance with
 * Add funds, and a Verified tag. "Verified" means this browser has joined (live: the background holds a server
 * session), which the server already requires for every bet. Verify opens the toolbar popup: joining stays
 * popup-only (the background refuses enrollment from the page).
 */
export function ProfileCard({
  onClose,
  onAddFunds,
  top,
}: {
  onClose: () => void;
  /** "Add funds" goes to the Wallet tab (owner request); falls back to the top-up dialog when absent. */
  onAddFunds?: () => void;
  /** Distance from the panel top, just below the header, so the card never covers the header buttons. */
  top?: number;
}) {
  const { controller, mode } = useEnv();
  const st = usePanel();
  const [profile] = useStoredValue<Profile | null>(PROFILE_KEY, null);
  const [verifyHint, setVerifyHint] = useState<string | null>(null);
  const [cardTheme] = useStoredValue<ThemeName>(THEME_KEY, 'calm');
  const odysseyCard = cardTheme === 'enrage';
  const name = profile?.display_name || st.backend?.displayName || null;
  const verified = mode === 'live' ? st.backend?.mode === 'LIVE' && st.backend.enrolled : Boolean(profile);
  const w = st.snapshot?.wallet;
  const canTopUp = verified && (st.snapshot?.modes.payment_mode === 'MOCK' || st.snapshot?.modes.payment_mode === 'STRIPE_TEST');
  const verify = async () => {
    setVerifyHint(null);
    const opened = await controller.openJoin();
    if (!opened) setVerifyHint(VERIFY_FALLBACK);
  };
  return (
    <div
      className="ft-profile"
      style={top !== undefined ? { top, maxHeight: `calc(100% - ${top + 12}px)` } : undefined}
      role="dialog"
      aria-label="Your FaZeTime profile"
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.preventDefault();
          onClose();
        }
      }}
    >
      <button type="button" className="ft-x ft-profile-close" aria-label="Close profile" onClick={onClose}>
        <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
          <path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" strokeWidth="2" />
        </svg>
      </button>
      <div className="ft-profile-top">
        <div className="ft-avatar-wrap">
          {odysseyCard && <Laurel size={50} />}
          <div className="ft-avatar" aria-hidden="true">
            <span>{initialsFor(name)}</span>
          </div>
          {odysseyCard && <Laurel size={50} flip />}
        </div>
        <div className="ft-profile-names">
          <b className="ft-profile-name">{name ?? 'No name yet'}</b>
          {verified ? (
            <span className="ft-verified" data-testid="profile-verified">
              <CheckIcon />
              Verified
            </span>
          ) : (
            <span className="ft-verified ft-verified--no" data-testid="profile-verified">
              Not verified
            </span>
          )}
          {profile?.claimed_twitch_login && (
            <span className="ft-fine">
              @{profile.claimed_twitch_login}
              {!verified && <em> (Twitch name not checked)</em>}
            </span>
          )}
        </div>
      </div>
      {!verified && (
        <div className="ft-verify">
          <p className="ft-hint ft-hint--warn">{VERIFY_NOTE}</p>
          <button type="button" className="ft-primary" onClick={() => void verify()}>
            Verify
          </button>
          {verifyHint && (
            <p className="ft-fine" role="status">
              {verifyHint}
            </p>
          )}
        </div>
      )}
      <div className="ft-profile-wallet">
        <div className="ft-profile-row">
          <span className="ft-profile-label">Available</span>
          <b className="ft-money ft-profile-balance" data-testid="profile-available">
            {w ? formatMinor(w.available_minor) : '…'}
          </b>
        </div>
        <button
          type="button"
          className="ft-primary ft-profile-add"
          disabled={!canTopUp}
          onClick={() => {
            if (onAddFunds) onAddFunds();
            else {
              controller.openTopUp('manual');
              onClose();
            }
          }}
        >
          {mode === 'live' ? 'Add funds' : 'Add demo funds (MOCK)'}
        </button>
        {!verified && <p className="ft-fine">Verify first to add funds.</p>}
      </div>
    </div>
  );
}

function ResizeHandle({ host, height, onChange }: { host: HTMLElement; height: number; onChange: (px: number) => void }) {
  const drag = useRef<{
    startY: number;
    startH: number;
    pointerId: number;
  } | null>(null);
  const [live, setLive] = useState<number | null>(null);
  const container = () => host.parentElement?.getBoundingClientRect().height ?? 0;
  const current = live ?? height;
  const max = Math.max(PANEL_MIN_PX, container() - CHAT_MIN_PX);

  useEffect(() => {
    if (live === null) return;
    host.style.transition = 'none'; // follow the pointer exactly while dragging
    host.style.height = `${live}px`;
  }, [live, host]);

  const commit = (px: number) => onChange(clampPanelHeight(px, container()));
  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    drag.current = {
      startY: e.clientY,
      startH: host.getBoundingClientRect().height,
      pointerId: e.pointerId,
    };
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
    host.style.transition = `height ${COLLAPSE_MS}ms cubic-bezier(0.2, 0.8, 0.2, 1)`;
  };
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const steps: Record<string, number> = {
      ArrowUp: -KEY_STEP_PX,
      ArrowDown: KEY_STEP_PX,
      PageUp: -PAGE_STEP_PX,
      PageDown: PAGE_STEP_PX,
    };
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
  const [walletTheme] = useStoredValue<ThemeName>(THEME_KEY, 'calm');
  const odysseyWallet = walletTheme === 'enrage';
  const w = st.snapshot?.wallet;
  return (
    <div>
      <div className="ft-wallet-grid">
        <div className="ft-stat">
          <span>
            {odysseyWallet && <Amphora size={14} />}
            Available
          </span>
          <b className="ft-money">{w ? formatMinor(w.available_minor) : '…'}</b>
        </div>
        <div className="ft-stat">
          <span>In play</span>
          <b>{w ? formatMinor(w.in_play_minor) : '…'}</b>
        </div>
      </div>
      {st.snapshot?.modes.payment_mode === 'MOCK' || st.snapshot?.modes.payment_mode === 'STRIPE_TEST' ? (
        <button type="button" className="ft-primary" onClick={() => controller.openTopUp('manual')}>
          {mode === 'live' ? 'Add funds' : 'Add demo funds (MOCK)'}
        </button>
      ) : (
        <button type="button" className="ft-primary" disabled>
          Top-ups aren't available yet
        </button>
      )}
      <p className="ft-fine">
        {mode === 'live' ? TEST_CREDITS_NOTE : 'Demo funds only. Not money, cannot be withdrawn, and only valid in this demo run.'}
      </p>
    </div>
  );
}

export interface MapStop {
  item: RedeemItem;
  locked: boolean;
  /** Minor units still needed to unlock (0 when unlocked or when rewards are unavailable). */
  needMinor: number;
}

/**
 * The Redeem "journey": rewards as stops along a route, cheapest first. A stop is unlocked when the viewer can
 * afford it and rewards are available; otherwise it is locked (and says how much is still needed).
 * Display only: the server still decides every redemption.
 */
export function redeemMap(items: readonly RedeemItem[], availableMinor: number | null, unavailable: boolean): MapStop[] {
  return [...items]
    .sort((a, b) => a.price_minor - b.price_minor)
    .map((item) => {
      const affordable = availableMinor !== null && availableMinor >= item.price_minor;
      const locked = unavailable || !affordable;
      const needMinor = !unavailable && availableMinor !== null && !affordable ? item.price_minor - availableMinor : 0;
      return { item, locked, needMinor };
    });
}

function LockIcon({ open }: { open: boolean }) {
  return (
    <svg viewBox="0 0 16 18" width="16" height="18" aria-hidden="true">
      <path d={open ? 'M4 8V5.5a4 4 0 0 1 7.6-1.8' : 'M4 8V5.5a4 4 0 0 1 8 0V8'} fill="none" stroke="currentColor" strokeWidth="2" />
      <rect x="1.5" y="8" width="13" height="9" rx="1.5" fill="currentColor" />
      <rect x="7" y="11" width="2" height="3.2" fill="var(--ft-map-keyhole, #000)" />
    </svg>
  );
}

function PinIcon() {
  return (
    <svg viewBox="0 0 16 18" width="15" height="17" aria-hidden="true">
      <path d="M8 17s6-6.2 6-10.2A6 6 0 0 0 2 6.8C2 10.8 8 17 8 17z" fill="currentColor" />
      <circle cx="8" cy="6.8" r="2.2" fill="var(--ft-map-keyhole, #000)" />
    </svg>
  );
}

/**
 * Where the ship sails: on the leg into the first locked stop, as far along as the balance reaches between the
 * last reached price and that stop's price. All reached: docked at the end of the last leg. Rewards unavailable or
 * balance unknown: just leaving port. Returns the leg index and the position along it (0..1).
 */
export function shipPosition(stops: readonly MapStop[], availableMinor: number | null, unavailable: boolean): { leg: number; t: number } | null {
  if (stops.length === 0) return null;
  if (unavailable || availableMinor === null) return { leg: 0, t: 0.12 };
  const next = stops.findIndex((s) => s.locked);
  if (next === -1) return { leg: stops.length - 1, t: 0.92 };
  const from = next === 0 ? 0 : stops[next - 1]!.item.price_minor;
  const to = stops[next]!.item.price_minor;
  const frac = to > from ? (availableMinor - from) / (to - from) : 0;
  return { leg: next, t: Math.min(0.88, Math.max(0.12, frac)) };
}

/** A point on the leg's curve, as (x % of width, y px), for t in 0..1. */
function legPoint(fromLeft: boolean, t: number): { x: number; y: number } {
  const [x0, x3] = fromLeft ? [9, 91] : [91, 9];
  const u = 1 - t;
  const x = u * u * u * x0 + 3 * u * u * t * x0 + 3 * u * t * t * x3 + t * t * t * x3;
  const y = 3 * u * u * t * 22 + 3 * u * t * t * 10 + t * t * t * 32;
  return { x, y };
}

/** Odyssey ship, after the owner's reference: square sail with a bordered panel, seam and diamond emblem,
 *  a pennant, rigging, a row of rowers and oars, and a curved hull with raised prow and stern. */
function ShipIcon() {
  return (
    <svg viewBox="0 0 60 52" width="50" height="44" aria-hidden="true">
      <g stroke="currentColor" strokeWidth="0.9" fill="none" opacity="0.8">
        <path d="M30 3L13 35M30 3L48 35" />
      </g>
      <path d="M30 2v34" stroke="currentColor" strokeWidth="1.6" />
      <path d="M30 2.5l10 3.2-10 3.2z" fill="currentColor" />
      <path d="M17 11h26l-1.6 19.5c-3.8 1.4-19 1.4-22.8 0z" fill="var(--ft-map-sail, currentColor)" stroke="currentColor" strokeWidth="1" />
      <path d="M19.5 13.5h21l-1.3 15c-3.3 1-15.1 1-18.4 0z" fill="none" stroke="var(--ft-map-sail-mark, #f4eee3)" strokeWidth="0.8" opacity="0.85" />
      <path d="M30 11v21" stroke="var(--ft-map-sail-mark, #f4eee3)" strokeWidth="0.7" opacity="0.7" />
      <path d="M30 16.2l4 4.6-4 4.6-4-4.6z" fill="var(--ft-map-sail, currentColor)" stroke="var(--ft-map-sail-mark, #f4eee3)" strokeWidth="1" />
      <circle cx="30" cy="20.8" r="1.4" fill="var(--ft-map-sail-mark, #f4eee3)" />
      <g fill="currentColor">
        {[17, 22, 27, 33, 38, 43].map((x) => (
          <g key={x}>
            <circle cx={x} cy="32.6" r="1.9" />
            <path d={`M${x - 1.6} 37v-2.4c0-1 .7-1.6 1.6-1.6s1.6.6 1.6 1.6V37z`} />
          </g>
        ))}
      </g>
      <g stroke="currentColor" strokeWidth="1.1">
        {[15, 21, 27, 33, 39, 45].map((x) => (
          <path key={x} d={`M${x} 39l-6 9`} />
        ))}
      </g>
      <path
        d="M3 31.5c2.2 0 3.2 2.3 5.4 4.5h43.4c2.5-1.3 4.3-3.8 5.6-6.8l1.6.6c-1.5 6.1-5.5 11.7-12 12.7H14.2C8.6 42.5 4.6 38 3 31.5z"
        fill="currentColor"
      />
      <path d="M11 39.2h38" stroke="var(--ft-map-sail-mark, #f4eee3)" strokeWidth="0.9" opacity="0.8" />
      <path
        d="M2 49c3 0 3-1.5 6-1.5s3 1.5 6 1.5 3-1.5 6-1.5 3 1.5 6 1.5 3-1.5 6-1.5 3 1.5 6 1.5 3-1.5 6-1.5 3 1.5 6 1.5"
        fill="none"
        stroke="var(--ft-map-wake, currentColor)"
        strokeWidth="1.2"
        opacity="0.7"
      />
    </svg>
  );
}

/** One leg of the route between two stops, curving to the other side; it may carry the ship. */
function MapLeg({ fromLeft, done, ship }: { fromLeft: boolean; done: boolean; ship?: number }) {
  const d = fromLeft ? 'M 9 0 C 9 22, 91 10, 91 32' : 'M 91 0 C 91 22, 9 10, 9 32';
  const at = ship !== undefined ? legPoint(fromLeft, ship) : null;
  return (
    <div className="ft-map-legwrap">
      <svg className={`ft-map-leg${done ? ' ft-map-leg--done' : ''}`} viewBox="0 0 100 32" preserveAspectRatio="none" aria-hidden="true">
        <path d={d} vectorEffect="non-scaling-stroke" />
      </svg>
      {at && (
        <span
          className="ft-map-ship"
          role="img"
          aria-label="Your ship: you are here"
          data-dir={fromLeft ? 'right' : 'left'}
          style={{ left: `${at.x}%`, top: at.y }}
        >
          <span className="ft-map-ship-bob">
            <ShipIcon />
          </span>
        </span>
      )}
    </div>
  );
}

function Bullseye() {
  return (
    <svg viewBox="0 0 60 60" width="56" height="56" aria-hidden="true" className="ft-bullseye">
      <circle cx="30" cy="30" r="28" className="ft-ring-a" />
      <circle cx="30" cy="30" r="22" className="ft-ring-b" />
      <circle cx="30" cy="30" r="16" className="ft-ring-a" />
      <circle cx="30" cy="30" r="10" className="ft-ring-b" />
      <circle cx="30" cy="30" r="4.5" className="ft-ring-a" />
    </svg>
  );
}

function Reticle() {
  return (
    <svg viewBox="0 0 60 60" width="64" height="64" aria-hidden="true" className="ft-reticle">
      <circle cx="30" cy="30" r="24" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="30" cy="30" r="13" fill="none" stroke="currentColor" strokeWidth="1" opacity="0.7" />
      <path d="M30 0v20M30 40v20M0 30h20M40 30h20" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="30" cy="30" r="2.2" fill="#fff" className="ft-laser-dot" />
    </svg>
  );
}

/**
 * FaZe side of Redeem (owner request): a shooting range. Each reward is a lane with a target, nearest (cheapest)
 * first; affordable targets can be fired at (= Redeem), the rest are locked. The Odyssey side keeps the voyage map.
 */
function TargetRange({ stops, available, unavailable }: { stops: MapStop[]; available: number | null; unavailable: boolean }) {
  const { controller } = useEnv();
  const { busyItem } = usePanel().redeem;
  return (
    <div className="ft-range" aria-label="Rewards range">
      <div className="ft-range-head">
        <span className="ft-range-title">Shooting range</span>
        <span className="ft-range-ammo">
          Ammo <b className="ft-money">{available !== null ? formatMinor(available) : '…'}</b>
        </span>
      </div>
      <ol className="ft-lanes">
        {stops.map((stop, i) => (
          <li
            key={stop.item.item_id}
            className={`ft-lane${stop.locked ? ' ft-lane--locked' : ''}${busyItem === stop.item.item_id ? ' ft-lane--firing' : ''}`}
          >
            <span className="ft-lane-dist" aria-hidden="true">
              {(i + 1) * 10}m
            </span>
            <span className="ft-target" role="img" aria-label={stop.locked ? 'Locked target' : 'Target in range'}>
              <Bullseye />
              {stop.locked ? (
                <span className="ft-target-lock">
                  <LockIcon open={false} />
                </span>
              ) : (
                <Reticle />
              )}
            </span>
            <div className="ft-lane-body">
              <strong>{stop.item.title}</strong>
              <p>{stop.item.description}</p>
              <div className="ft-lane-foot">
                <span className="ft-map-price">{formatMinor(stop.item.price_minor)}</span>
                {stop.locked ? (
                  <span className="ft-map-need">
                    {unavailable ? 'Not available yet' : stop.needMinor > 0 ? `${formatMinor(stop.needMinor)} more to unlock` : 'Locked'}
                  </span>
                ) : (
                  <button type="button" className="ft-fire" disabled={busyItem !== null} onClick={() => void controller.redeem(stop.item.item_id)}>
                    {busyItem === stop.item.item_id ? 'Firing…' : 'Fire'}
                  </button>
                )}
              </div>
            </div>
          </li>
        ))}
      </ol>
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
  const available = st.snapshot?.wallet.available_minor ?? null;
  const stops = redeemMap(st.catalog ?? [], available, unavailable);
  const ship = shipPosition(stops, available, unavailable);
  const [theme] = useStoredValue<ThemeName>(THEME_KEY, 'calm');
  const odyssey = theme === 'enrage';
  return (
    <div>
      {mode === 'live' && unavailable ? (
        <p className="ft-fine">Rewards aren't available yet. Every stop is locked for now.</p>
      ) : (
        <p className="ft-fine">Tiny fixed demo catalog. Codes are random and NON-REDEEMABLE: no store, coupon or prize exists.</p>
      )}
      {!odyssey && <TargetRange stops={stops} available={available} unavailable={unavailable} />}
      {odyssey && (
        <ol className="ft-map" aria-label="Rewards journey">
          <li className="ft-map-row ft-map-row--left ft-map-start">
            <span className="ft-map-node ft-map-node--start" aria-hidden="true">
              <PinIcon />
            </span>
            <div className="ft-map-card">
              <strong>Home port</strong>
              <p>
                Available <b className="ft-money">{available !== null ? formatMinor(available) : '…'}</b>
              </p>
            </div>
          </li>
          {stops.map((stop, i) => {
            const left = i % 2 === 1; // the start is on the left, so the first stop sits on the right
            return (
              <li key={stop.item.item_id} className={`ft-map-row ft-map-row--${left ? 'left' : 'right'}${stop.locked ? ' ft-map-row--locked' : ''}`}>
                <MapLeg fromLeft={!left} done={!stop.locked} ship={ship?.leg === i ? ship.t : undefined} />
                <div className="ft-map-stop">
                  <span
                    className={`ft-map-node${stop.locked ? ' ft-map-node--locked' : ' ft-map-node--open'}`}
                    role="img"
                    aria-label={stop.locked ? 'Locked' : 'Unlocked'}
                  >
                    <LockIcon open={!stop.locked} />
                  </span>
                  <div className="ft-map-card">
                    <strong>{stop.item.title}</strong>
                    <p>{stop.item.description}</p>
                    <div className="ft-map-foot">
                      <span className="ft-map-price">{formatMinor(stop.item.price_minor)}</span>
                      {stop.locked ? (
                        <span className="ft-map-need">
                          {unavailable ? 'Not available yet' : stop.needMinor > 0 ? `${formatMinor(stop.needMinor)} more to unlock` : 'Locked'}
                        </span>
                      ) : (
                        <button
                          type="button"
                          className="ft-secondary"
                          disabled={busyItem !== null}
                          onClick={() => void controller.redeem(stop.item.item_id)}
                        >
                          {busyItem === stop.item.item_id ? 'Redeeming…' : 'Redeem'}
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      )}
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
            Debited {formatMinor(receipt.price_minor)} of demo funds
            {receipt.replayed ? ' (same request replayed; charged once)' : ''}. Not valid anywhere.
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
  if (st.snapshot?.modes.payment_mode === 'STRIPE_TEST') return <StripeTopUpDialog />;
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
            {t.neededMinor ? `You need ${formatMinor(t.neededMinor)} more for that bet. ` : ''}
            Topping up does not hold your bet or the market; it may close before you are back.
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
            Custom amount ({formatMinor(limits.topup_min_minor)} to {formatMinor(limits.topup_max_minor)}, steps of{' '}
            {formatMinor(limits.topup_step_minor)})
            <input className="ft-input" inputMode="decimal" value={customText} placeholder="20" onChange={(e) => setCustomText(e.target.value)} />
          </label>
        )}
        {problem && choice === 'custom' && customText !== '' && (
          <div className="ft-field-error">
            {describeAmountProblem(problem, limits.topup_min_minor, limits.topup_max_minor, limits.topup_step_minor)}
          </div>
        )}
        {currencySymbol() === '₯' && <p className="ft-fine">1 ₯ = $1 in test credits.</p>}
        <button
          type="button"
          className="ft-primary"
          disabled={busy || problem !== null || amount === null}
          onClick={() => amount !== null && void controller.submitTopUp(amount)}
        >
          {busy ? 'Adding…' : 'FaZe Up!'}
        </button>
        {t.message && (
          <div
            className={`ft-status ${t.status === 'credited' ? 'ft-status--ok' : t.status === 'error' ? 'ft-status--err' : 'ft-status--wait'}`}
            role="status"
          >
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

/** Buttons for the tracked top-up's suggested follow-up. */
function TopUpActions({ action, terminal, onDone }: { action: 'REOPEN' | 'CHECK' | null; terminal: boolean; onDone?: () => void }) {
  const { controller } = useEnv();
  return (
    <>
      {action === 'REOPEN' && (
        <button type="button" className="ft-link" onClick={() => void controller.reopenTopUpCheckout()}>
          Open checkout
        </button>
      )}
      {action === 'CHECK' && (
        <button type="button" className="ft-link" onClick={() => void controller.checkTopUpAgain()}>
          Check again
        </button>
      )}
      {terminal && (
        <button type="button" className="ft-link" onClick={() => (onDone ? onDone() : void controller.dismissTopUpResult())}>
          OK
        </button>
      )}
    </>
  );
}

/** Panel-level line for a Stripe test top-up while the dialog is closed (e.g. after Stripe's return). */
export function TopUpNotice() {
  const st = usePanel();
  const t = st.pendingTopUp;
  if (!t) return null;
  const { controller } = useEnv();
  const copy = describeTopUp(t, st.checkoutClosedFor === t.topup_id);
  if (!copy.terminal && st.hiddenTopUpFor === t.topup_id) return null;
  return (
    <div className={`ft-notice${copy.tone === 'err' ? ' ft-notice--warn' : ''}`} role="status">
      <span>{copy.text}</span>
      <span className="ft-notice-actions">
        <TopUpActions action={copy.action} terminal={copy.terminal} />
        {!copy.terminal && (
          <button
            type="button"
            className="ft-x"
            aria-label="Hide this top-up notice"
            title="Hide. If you still pay in the Stripe tab, the credits will arrive anyway."
            onClick={() => controller.hidePendingTopUp()}
          >
            <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
              <path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" strokeWidth="2" />
            </svg>
          </button>
        )}
      </span>
    </div>
  );
}

/**
 * P6 live top-up (CONTRACTS 9.18). "FaZe Up!" asks the background to create the top-up; the background
 * opens Stripe-hosted Checkout in a new tab. No card fields exist here: card entry happens only on
 * Stripe's page. Credits appear only after the SERVER reports CREDITED, and nothing re-places a bet.
 */
export function StripeTopUpDialog() {
  const { controller } = useEnv();
  const st = usePanel();
  const limits = st.snapshot?.limits;
  const t = st.topUp;
  const track = st.pendingTopUp;
  const [choice, setChoice] = useState<number | 'custom'>(() => limits?.topup_presets_minor[0] ?? 0);
  const [customText, setCustomText] = useState('');
  const firstRef = useRef<HTMLButtonElement>(null);
  useEffect(() => firstRef.current?.focus(), []);
  if (!limits) return null;
  const amount = choice === 'custom' ? parseDollarsToMinor(customText) : choice;
  const problem = checkTopUp(amount, limits);
  const creating = t.status === 'submitting' || (track?.status === 'SUBMITTING' && track.watching);
  const copy = track ? describeTopUp(track, st.checkoutClosedFor === track.topup_id) : null;
  const close = () => {
    if (copy?.terminal) void controller.dismissTopUpResult();
    controller.closeTopUp();
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      close();
    }
  };
  return (
    <div className="ft-backdrop" onKeyDown={onKey}>
      <div className="ft-dialog" role="dialog" aria-modal="false" aria-labelledby="ft-topup-title">
        <div className="ft-row">
          <h4 id="ft-topup-title">Add funds</h4>
        </div>
        {t.reason === 'insufficient' && (
          <p className="ft-hint ft-hint--warn">
            {t.neededMinor ? `You need ${formatMinor(t.neededMinor)} more for that bet. ` : ''}
            Topping up does not hold your bet or the market; it may close before you are back.
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
              disabled={creating}
              onClick={() => setChoice(p)}
            >
              {formatMinor(p).replace('.00', '')}
            </button>
          ))}
          <button type="button" className="ft-amount" aria-pressed={choice === 'custom'} disabled={creating} onClick={() => setChoice('custom')}>
            Custom
          </button>
        </div>
        {choice === 'custom' && (
          <label className="ft-label">
            Custom amount ({formatMinor(limits.topup_min_minor)} to {formatMinor(limits.topup_max_minor)}, steps of{' '}
            {formatMinor(limits.topup_step_minor)})
            <input className="ft-input" inputMode="decimal" value={customText} placeholder="20" onChange={(e) => setCustomText(e.target.value)} />
          </label>
        )}
        {problem && choice === 'custom' && customText !== '' && (
          <div className="ft-field-error">
            {describeAmountProblem(problem, limits.topup_min_minor, limits.topup_max_minor, limits.topup_step_minor)}
          </div>
        )}
        {currencySymbol() === '₯' && <p className="ft-fine">1 ₯ = $1 in test credits. Stripe's checkout page shows dollars.</p>}
        <button
          type="button"
          className="ft-primary"
          disabled={creating || problem !== null || amount === null}
          onClick={() => amount !== null && void controller.submitTopUp(amount)}
        >
          {creating ? 'Opening checkout…' : 'FaZe Up!'}
        </button>
        <p className="ft-hint">Opens Stripe's secure checkout in a new tab. Card details are entered only there.</p>
        {t.message && (
          <div className={`ft-status ${t.status === 'error' ? 'ft-status--err' : 'ft-status--wait'}`} role="status">
            {t.message}
          </div>
        )}
        {copy && (
          <div className={`ft-status ft-status--${copy.tone}`} role="status">
            <span>{copy.text}</span> <TopUpActions action={copy.action} terminal={false} />
          </div>
        )}
        {copy?.tone === 'ok' && t.reason === 'insufficient' && (
          <p className="ft-hint">Your bet was not placed. Check the market and confirm it again.</p>
        )}
        <p className="ft-fine">{TEST_CREDITS_NOTE}</p>
        <button type="button" className="ft-secondary" onClick={close} disabled={t.status === 'submitting'}>
          {copy?.terminal ? 'Done' : 'Close'}
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
