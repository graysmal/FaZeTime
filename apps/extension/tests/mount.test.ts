import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MountController, type MountDeps } from '../src/content/mount';

// Mirrors the live Twitch structure recorded in src/content/anchors.ts.
function twitchDom(doc: Document, { chat = true, player = true } = {}) {
  doc.body.innerHTML = `
    <div class="persistent-player">${player ? '<div data-a-target="video-player" style="position:absolute"><div class="video-player__container"></div></div>' : ''}</div>
    <aside id="live-page-chat">${chat ? '<div class="stream-chat"><div class="stream-chat-header">Stream Chat</div><section class="chat-room" data-test-selector="chat-room-component-layout"></section></div>' : ''}</aside>`;
}

describe('MountController (P1-A / P1-E)', () => {
  let path = '/somechannel';
  let renders: { panel: number; overlay: number; unmounts: number };
  let ctl: MountController;

  const make = (over: Partial<MountDeps> = {}) =>
    new MountController({
      doc: document,
      getPath: () => path,
      instanceId: 'inst-a',
      css: '.x{}',
      coalesceMs: 5,
      attachTimeoutMs: 200,
      renderPanel: () => {
        renders.panel += 1;
        return { unmount: () => void (renders.unmounts += 1) };
      },
      renderOverlay: () => {
        renders.overlay += 1;
        return { unmount: () => void (renders.unmounts += 1) };
      },
      ...over,
    });
  const hosts = (slot: string) => document.querySelectorAll(`[data-fazetime-host="${slot}"]`);
  const flush = (ms = 30) => new Promise((r) => setTimeout(r, ms));

  beforeEach(() => {
    path = '/somechannel';
    renders = { panel: 0, overlay: 0, unmounts: 0 };
  });
  afterEach(() => ctl?.stop());

  it('mounts exactly once above chat and once over the video, and stays idempotent', async () => {
    twitchDom(document);
    ctl = make();
    ctl.start();
    ctl.start();
    ctl.check();
    ctl.check();
    await flush();
    expect(hosts('panel')).toHaveLength(1);
    expect(hosts('overlay')).toHaveLength(1);
    const panel = hosts('panel')[0]!;
    expect(panel.previousElementSibling?.classList.contains('stream-chat-header')).toBe(true);
    expect(panel.nextElementSibling?.classList.contains('chat-room')).toBe(true);
    expect(panel.shadowRoot?.querySelector('style')?.textContent).toBe('.x{}');
    expect(renders.panel).toBe(1);
    expect(renders.overlay).toBe(1);
    // Unrelated page mutations do not cause re-insertion.
    document.querySelector('.chat-room')!.appendChild(document.createElement('div'));
    await flush();
    expect(ctl.insertions).toBe(2);
  });

  it('SPA navigation unmounts cleanly and remounts once for the new channel', async () => {
    twitchDom(document);
    ctl = make();
    ctl.start();
    path = '/otherchannel';
    twitchDom(document); // Twitch re-renders the page.
    ctl.onLocationChange();
    await flush();
    expect(hosts('panel')).toHaveLength(1);
    expect(hosts('overlay')).toHaveLength(1);
    expect(ctl.state.channel).toBe('otherchannel');
    path = '/directory';
    ctl.onLocationChange();
    expect(hosts('panel')).toHaveLength(0);
    expect(hosts('overlay')).toHaveLength(0);
    expect(ctl.state.observing).toBe(false); // Observer detached off channel pages.
  });

  it('detects a missed navigation from the observer path check', async () => {
    twitchDom(document);
    ctl = make();
    ctl.start();
    path = '/thirdchannel';
    document.body.appendChild(document.createElement('div')); // Any mutation triggers a coalesced check.
    await flush();
    expect(ctl.state.channel).toBe('thirdchannel');
    expect(hosts('panel')).toHaveLength(1);
  });

  it('re-inserts once if Twitch removes the host, then gives up into a recoverable floating notice', async () => {
    twitchDom(document);
    ctl = make({ maxRemounts: 2 });
    ctl.start();
    for (let i = 0; i < 2; i++) {
      hosts('panel')[0]!.remove();
      await flush();
      expect(hosts('panel')).toHaveLength(1);
    }
    hosts('panel')[0]!.remove();
    await flush();
    expect(ctl.state).toMatchObject({ gaveUp: true, panel: 'floating', notice: 'reattach_paused' });
    expect(hosts('panel')).toHaveLength(1);
    ctl.retryAttach();
    expect(ctl.state).toMatchObject({ gaveUp: false, panel: 'chat' });
  });

  it('falls back to a floating panel when chat is missing past the bound, then moves into chat', async () => {
    twitchDom(document, { chat: false });
    ctl = make();
    ctl.start();
    expect(hosts('panel')).toHaveLength(0);
    await flush(260);
    expect(ctl.state).toMatchObject({ panel: 'floating', notice: 'chat_not_found' });
    document.querySelector('#live-page-chat')!.innerHTML =
      '<div class="stream-chat"><div class="stream-chat-header"></div><section class="chat-room" data-test-selector="chat-room-component-layout"></section></div>';
    await flush();
    expect(ctl.state.panel).toBe('chat');
    expect(hosts('panel')).toHaveLength(1);
  });

  it('removes hosts orphaned by an invalidated instance and cleans up on stop', async () => {
    twitchDom(document);
    const orphan = document.createElement('fazetime-root');
    orphan.setAttribute('data-fazetime-host', 'panel');
    orphan.setAttribute('data-fazetime-instance', 'old-instance');
    document.body.appendChild(orphan);
    ctl = make();
    ctl.start();
    expect(document.querySelectorAll('[data-fazetime-instance="old-instance"]')).toHaveLength(0);
    expect(hosts('panel')).toHaveLength(1);
    const spy = vi.spyOn(MutationObserver.prototype, 'disconnect');
    ctl.stop();
    expect(spy).toHaveBeenCalled();
    expect(document.querySelectorAll('[data-fazetime-host]')).toHaveLength(0);
    spy.mockRestore();
  });

  it('stops Twitch hotkeys from seeing key events typed in the panel', () => {
    twitchDom(document);
    ctl = make();
    ctl.start();
    const seen = vi.fn();
    document.addEventListener('keydown', seen);
    hosts('panel')[0]!.dispatchEvent(new KeyboardEvent('keydown', { key: 'f', bubbles: true }));
    expect(seen).not.toHaveBeenCalled();
    document.removeEventListener('keydown', seen);
  });
});
