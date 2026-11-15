// Twitch content script: mount/lifecycle shell only. It renders the bundled ShadowRoot panel and the
// over-video dropdown, and talks to the background over a runtime Port. It never calls an API.
import { StrictMode, type ReactElement } from 'react';
import { createRoot } from 'react-dom/client';
import { browser } from 'wxt/browser';
import { defineContentScript } from 'wxt/utils/define-content-script';
import css from '../../src/ui/styles.css?inline';
import { BackgroundClient } from '../../src/api/client';
import { PORT_NAME, type PortLike } from '../../src/api/protocol';
import { MountController, type MountedView } from '../../src/content/mount';
import { FAZETIME_MODE, LIVE_CHANNEL } from '../../src/config';
import { PanelController } from '../../src/state/controller';
import { watchKey, wxtKV } from '../../src/storage';
import { EnvContext, type UiEnv } from '../../src/ui/hooks';
import { Overlay } from '../../src/ui/Overlay';
import { Panel } from '../../src/ui/Panel';
import { DIAMOND_CSS_VALUE, registerFonts } from '../../src/ui/theme';

export default defineContentScript({
  matches: ['https://www.twitch.tv/*'],
  runAt: 'document_idle',
  main(ctx) {
    const instanceId = crypto.randomUUID();
    registerFonts(document);
    let controller: PanelController | null = null;
    let client: BackgroundClient | null = null;
    let views = 0;
    const panelOpenListeners = new Set<() => void>();

    const ensureController = (): PanelController => {
      if (controller) return controller;
      const c = new BackgroundClient({
        connect: () => browser.runtime.connect({ name: PORT_NAME }) as unknown as PortLike,
        onPush: (msg) => controller?.onPush(msg),
        onConnection: (state) => controller?.onConnection(state),
        isValid: () => ctx.isValid,
      });
      client = c;
      controller = new PanelController(c, wxtKV);
      controller.start();
      return controller;
    };

    const releaseController = () => {
      if (views > 0) return;
      controller?.dispose();
      client?.dispose();
      controller = null;
      client = null;
    };

    const makeEnv = (channel: string): UiEnv => ({
      controller: ensureController(),
      kv: wxtKV,
      watch: watchKey,
      channel,
      doc: document,
      mode: FAZETIME_MODE,
      requestPanelOpen: () => panelOpenListeners.forEach((cb) => cb()),
      onPanelOpenRequest: (cb) => {
        panelOpenListeners.add(cb);
        return () => panelOpenListeners.delete(cb);
      },
    });

    const renderInto = (root: HTMLElement, channel: string, node: (env: UiEnv) => ReactElement): MountedView => {
      const env = makeEnv(channel);
      root.style.setProperty('--ft-diamond', DIAMOND_CSS_VALUE);
      const reactRoot = createRoot(root);
      reactRoot.render(
        <StrictMode>
          <EnvContext.Provider value={env}>{node(env)}</EnvContext.Provider>
        </StrictMode>,
      );
      views += 1;
      return {
        unmount: () => {
          reactRoot.unmount();
          views -= 1;
          releaseController();
        },
      };
    };

    // Presence (live builds): visibility + player state every 15 s while a panel is mounted. The
    // background attaches the device ID and session and calls POST /v1/presence.
    const tabInstanceId = crypto.randomUUID().toLowerCase();
    let presenceChannel: string | null = null;
    const playerState = (): 'PLAYING' | 'PAUSED' | 'BUFFERING' | 'UNKNOWN' => {
      const video = document.querySelector<HTMLVideoElement>('[data-a-target="video-player"] video');
      if (!video) return 'UNKNOWN';
      if (video.paused) return 'PAUSED';
      return video.readyState < 3 ? 'BUFFERING' : 'PLAYING';
    };
    const sendPresence = () => {
      if (FAZETIME_MODE !== 'live' || !client || !presenceChannel) return;
      void client.presence({
        tab_instance_id: tabInstanceId,
        observed_channel_login: presenceChannel,
        page_visibility: document.visibilityState === 'visible' ? 'VISIBLE' : 'HIDDEN',
        player_state: playerState(),
      });
    };
    ctx.setInterval(sendPresence, 15_000);
    ctx.addEventListener(document, 'visibilitychange', sendPresence);

    // P6: Stripe's success/cancel return URL carries ?fazetime_topup=<id>. It is ONLY a hint to poll the
    // server now; it never credits, and the status shown is always the server's.
    let lastTopUpHint: string | null = null;
    const checkTopUpHint = () => {
      if (FAZETIME_MODE !== 'live' || !controller) return;
      const params = new URLSearchParams(location.search);
      const id = params.get('fazetime_topup');
      if (!id || !/^top_[0-9a-f]{32}$/.test(id) || id === lastTopUpHint) return;
      lastTopUpHint = id;
      void controller.topUpHint(id, { closed: params.get('fazetime_result') === 'cancel' });
    };

    const mounter = new MountController({
      doc: document,
      getPath: () => location.pathname,
      allowedChannel: FAZETIME_MODE === 'live' ? LIVE_CHANNEL : null,
      instanceId,
      css,
      renderPanel: ({ host, root, placement, notice, channel, retryAttach }) => {
        const view = renderInto(root, channel, () => <Panel host={host} placement={placement} notice={notice} retryAttach={retryAttach} />);
        presenceChannel = channel;
        checkTopUpHint();
        ctx.setTimeout(sendPresence, 1500);
        return {
          unmount: () => {
            presenceChannel = null;
            view.unmount();
          },
        };
      },
      renderOverlay: ({ host, root, channel }) => renderInto(root, channel, () => <Overlay host={host} />),
      log: (message) => console.info('[FaZeTime]', message),
    });

    mounter.start();
    // SPA navigation: WXT's watcher (Navigation API), popstate, plus a cheap 1 s route poll as a
    // fallback. Each only re-reads location.pathname; the DOM is touched only on a real change.
    const onNav = () => {
      mounter.onLocationChange();
      checkTopUpHint();
      ctx.setTimeout(() => mounter.onLocationChange(), 60);
    };
    ctx.addEventListener(window, 'wxt:locationchange', onNav);
    ctx.addEventListener(window, 'popstate', onNav);
    ctx.setInterval(() => mounter.onLocationChange(), 1000);
    // Extension reload/update or a newer instance: remove every host, observer, timer and port.
    ctx.onInvalidated(() => {
      mounter.stop();
      views = 0;
      releaseController();
    });
  },
});
