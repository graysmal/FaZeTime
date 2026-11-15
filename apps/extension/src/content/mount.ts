// Mount lifecycle for Twitch's SPA (P1-A, P1-E).
// - Idempotent: at most one panel host and one overlay host per page, tagged with this instance ID;
//   hosts left by an invalidated previous instance (extension reload) are removed.
// - ONE MutationObserver, attached only on channel pages; callbacks are coalesced (<= ~6 checks/s)
//   and each check does a few querySelector calls.
// - Route changes unmount everything and start a fresh, time-bounded attach.
// - If chat is not found within the bound, mount a floating panel. If Twitch keeps removing our
//   host, stop re-inserting after a small budget and show a recoverable notice instead.

import { channelFromPath } from '../lib/route';
import { findPanelAnchor, findPlayerAnchor, type PanelAnchor } from './anchors';

export const HOST_TAG = 'fazetime-root';
export type Placement = 'chat' | 'floating';
export type PanelNotice = 'chat_not_found' | 'reattach_paused' | null;

export interface MountedView {
  unmount(): void;
}

export interface PanelRenderArgs {
  host: HTMLElement;
  root: HTMLElement;
  placement: Placement;
  notice: PanelNotice;
  channel: string;
  retryAttach: () => void;
}

export interface OverlayRenderArgs {
  host: HTMLElement;
  root: HTMLElement;
  channel: string;
}

export interface MountDeps {
  doc: Document;
  getPath: () => string;
  /** Live builds mount only on this channel (lowercase login); null = any channel page. */
  allowedChannel?: string | null;
  instanceId: string;
  css: string;
  renderPanel: (args: PanelRenderArgs) => MountedView;
  renderOverlay?: (args: OverlayRenderArgs) => MountedView;
  attachTimeoutMs?: number;
  maxRemounts?: number;
  remountWindowMs?: number;
  coalesceMs?: number;
  now?: () => number;
  log?: (message: string) => void;
}

interface Mounted {
  host: HTMLElement;
  view: MountedView;
}

const KEY_EVENTS = ['keydown', 'keyup', 'keypress'] as const;

export function createHost(doc: Document, slot: 'panel' | 'overlay', instanceId: string, css: string) {
  const host = doc.createElement(HOST_TAG);
  host.setAttribute('data-fazetime-host', slot);
  host.setAttribute('data-fazetime-instance', instanceId);
  const shadow = host.attachShadow({ mode: 'open' });
  const style = doc.createElement('style');
  style.textContent = css;
  shadow.appendChild(style);
  const root = doc.createElement('div');
  root.className = 'ft-root';
  shadow.appendChild(root);
  // Typing in the panel must not trigger Twitch hotkeys. Tab/focus movement is unaffected.
  for (const type of KEY_EVENTS) host.addEventListener(type, (e) => e.stopPropagation());
  return { host, root };
}

export class MountController {
  private channel: string | null = null;
  private panel: (Mounted & { placement: Placement; notice: PanelNotice }) | null = null;
  private overlay: (Mounted & { anchor: Element }) | null = null;
  private observer: MutationObserver | null = null;
  private scheduled: ReturnType<typeof setTimeout> | null = null;
  private deadlineTimer: ReturnType<typeof setTimeout> | null = null;
  private deadline = 0;
  private remountTimes: number[] = [];
  private gaveUp = false;
  private stopped = false;
  /** Count of host insertions, for tests and diagnostics. */
  insertions = 0;

  constructor(private readonly deps: MountDeps) {}

  private channelFor(path: string): string | null {
    const ch = channelFromPath(path);
    const allowed = this.deps.allowedChannel ?? null;
    return allowed && ch !== allowed ? null : ch;
  }

  private get now(): number {
    return (this.deps.now ?? Date.now)();
  }

  start(): void {
    this.stopped = false;
    this.removeForeignHosts();
    this.onLocationChange();
  }

  stop(): void {
    this.stopped = true;
    this.disconnect();
    this.unmountAll();
    this.channel = null;
  }

  /** Call on SPA navigation; also re-checked from the observer in case an event is missed. */
  onLocationChange(): void {
    if (this.stopped) return;
    const next = this.channelFor(this.deps.getPath());
    if (next === this.channel) {
      this.schedule();
      return;
    }
    this.unmountAll();
    this.channel = next;
    this.gaveUp = false;
    this.remountTimes = [];
    if (!next) {
      this.disconnect();
      return;
    }
    this.deadline = this.now + (this.deps.attachTimeoutMs ?? 10_000);
    this.observe();
    this.check();
  }

  retryAttach = (): void => {
    if (this.stopped || !this.channel) return;
    this.unmountAll();
    this.gaveUp = false;
    this.remountTimes = [];
    this.deadline = this.now + (this.deps.attachTimeoutMs ?? 10_000);
    this.observe();
    this.check();
  };

  private observe(): void {
    if (this.observer) return;
    const target = this.deps.doc.body ?? this.deps.doc.documentElement;
    this.observer = new MutationObserver(() => this.schedule());
    this.observer.observe(target, { childList: true, subtree: true });
  }

  private disconnect(): void {
    this.observer?.disconnect();
    this.observer = null;
    if (this.scheduled !== null) clearTimeout(this.scheduled);
    this.scheduled = null;
    if (this.deadlineTimer !== null) clearTimeout(this.deadlineTimer);
    this.deadlineTimer = null;
  }

  private schedule(): void {
    if (this.stopped || this.scheduled !== null) return;
    this.scheduled = setTimeout(() => {
      this.scheduled = null;
      this.check();
    }, this.deps.coalesceMs ?? 150);
  }

  /** Remove hosts that belong to another (invalidated) content-script instance. */
  private removeForeignHosts(): void {
    for (const el of Array.from(this.deps.doc.querySelectorAll('[data-fazetime-host]'))) {
      if (el.getAttribute('data-fazetime-instance') !== this.deps.instanceId) el.remove();
    }
  }

  private allowRemount(): boolean {
    const now = this.now;
    const windowMs = this.deps.remountWindowMs ?? 60_000;
    this.remountTimes = this.remountTimes.filter((t) => now - t < windowMs);
    if (this.remountTimes.length >= (this.deps.maxRemounts ?? 5)) return false;
    this.remountTimes.push(now);
    return true;
  }

  check(): void {
    if (this.stopped) return;
    const current = this.channelFor(this.deps.getPath());
    if (current !== this.channel) {
      this.onLocationChange();
      return;
    }
    if (!this.channel) return;
    this.removeForeignHosts();
    const anchor = findPanelAnchor(this.deps.doc);

    if (this.panel && !this.panel.host.isConnected) {
      this.deps.log?.('panel host was removed by the page');
      this.unmountPanel();
      if (!this.allowRemount()) return this.giveUp();
    }
    if (this.gaveUp) return;
    if (this.panel?.placement === 'floating' && this.panel.notice === 'chat_not_found' && anchor) this.unmountPanel(); // Chat appeared late.
    if (!this.panel) {
      if (anchor) this.mountPanel('chat', null, anchor);
      else if (this.now >= this.deadline) {
        this.deps.log?.('chat anchor not found within the bound; using the floating panel');
        this.mountPanel('floating', 'chat_not_found', null);
      } else this.armDeadline();
    }

    if (!this.deps.renderOverlay) return;
    const player = findPlayerAnchor(this.deps.doc);
    if (this.overlay && (!this.overlay.host.isConnected || this.overlay.anchor !== player)) {
      this.unmountOverlay();
      if (!this.allowRemount()) return this.giveUp();
    }
    if (!this.overlay && player) this.mountOverlay(player);
  }

  private armDeadline(): void {
    if (this.deadlineTimer !== null) return;
    this.deadlineTimer = setTimeout(() => {
      this.deadlineTimer = null;
      this.check();
    }, Math.max(0, this.deadline - this.now) + 10);
  }

  private giveUp(): void {
    this.gaveUp = true;
    this.deps.log?.('Twitch keeps replacing the page area; stopped re-inserting (recoverable)');
    this.unmountAll();
    this.mountPanel('floating', 'reattach_paused', null);
  }

  private mountPanel(placement: Placement, notice: PanelNotice, anchor: PanelAnchor | null): void {
    const { doc, instanceId, css } = this.deps;
    if (doc.querySelector(`[data-fazetime-host="panel"][data-fazetime-instance="${instanceId}"]`)) return; // Never twice.
    const { host, root } = createHost(doc, 'panel', instanceId, css);
    host.setAttribute('data-fazetime-placement', placement);
    if (placement === 'chat' && anchor) {
      host.style.cssText = 'display:block;flex:0 0 auto;position:relative;z-index:1;min-height:0;';
      anchor.parent.insertBefore(host, anchor.before);
    } else {
      host.style.cssText = 'display:block;position:fixed;right:16px;bottom:16px;width:360px;max-height:72vh;z-index:2147483000;';
      (doc.body ?? doc.documentElement).appendChild(host);
    }
    this.insertions += 1;
    const view = this.deps.renderPanel({ host, root, placement, notice, channel: this.channel!, retryAttach: this.retryAttach });
    this.panel = { host, view, placement, notice };
  }

  private mountOverlay(player: Element): void {
    const { doc, instanceId, css } = this.deps;
    if (!this.deps.renderOverlay) return;
    if (doc.querySelector(`[data-fazetime-host="overlay"][data-fazetime-instance="${instanceId}"]`)) return;
    const { host, root } = createHost(doc, 'overlay', instanceId, css);
    host.style.cssText =
      'display:block;position:absolute;top:10px;left:50%;transform:translateX(-50%);z-index:20;max-width:min(440px, calc(100% - 24px));';
    player.appendChild(host);
    this.insertions += 1;
    const view = this.deps.renderOverlay({ host, root, channel: this.channel! });
    this.overlay = { host, view, anchor: player };
  }

  private unmountPanel(): void {
    if (!this.panel) return;
    try {
      this.panel.view.unmount();
    } finally {
      this.panel.host.remove();
      this.panel = null;
    }
  }

  private unmountOverlay(): void {
    if (!this.overlay) return;
    try {
      this.overlay.view.unmount();
    } finally {
      this.overlay.host.remove();
      this.overlay = null;
    }
  }

  private unmountAll(): void {
    this.unmountPanel();
    this.unmountOverlay();
    if (this.deadlineTimer !== null) clearTimeout(this.deadlineTimer);
    this.deadlineTimer = null;
  }

  /** Diagnostics for tests. */
  get state() {
    return {
      channel: this.channel,
      panel: this.panel?.placement ?? null,
      notice: this.panel?.notice ?? null,
      overlay: Boolean(this.overlay),
      observing: Boolean(this.observer),
      gaveUp: this.gaveUp,
    };
  }
}
