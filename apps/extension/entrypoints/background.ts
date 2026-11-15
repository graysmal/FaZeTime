// Background service worker. It owns the backend adapter: every API call happens here, never in a
// content script (extension origin avoids mixed content, page CORS and local-network prompts).
// - mock builds: MockBackend with state in storage.session.
// - live builds: LiveBackend against WXT_FAZETIME_API_BASE; the session token stays in background storage.
// Service-worker memory is disposable: tabs resync from snapshots on reconnect.
import { browser } from 'wxt/browser';
import { defineBackground } from 'wxt/utils/define-background';
import { storage } from 'wxt/utils/storage';
import { attachPopupHandler, attachRouter, type MessageRuntimeLike, type RuntimeLike } from '../src/api/router';
import { API_BASE, EXTENSION_VERSION, FAZETIME_MODE, LIVE_CHANNEL } from '../src/config';
import { LiveBackend } from '../src/live/backend';
import { wxtLiveStore } from '../src/live/store';
import { MockBackend, type MockState } from '../src/mock/backend';

const MOCK_STATE_KEY = 'session:fazetime.mockState';

export default defineBackground(() => {
  const runtime = browser.runtime as unknown as RuntimeLike & MessageRuntimeLike;
  if (FAZETIME_MODE === 'live') {
    const adapter = new LiveBackend({
      apiBase: API_BASE,
      channel: LIVE_CHANNEL,
      extensionVersion: EXTENSION_VERSION,
      store: wxtLiveStore,
      log: (msg) => console.info('[FaZeTime live]', msg), // Never logs tokens, tickets, invite codes or Checkout URLs.
      // P6: Stripe-hosted Checkout opens in a new tab from the background. tabs.create needs no permission.
      openTab: async (url) => {
        await browser.tabs.create({ url, active: true });
      },
    });
    attachRouter(adapter, runtime);
    attachPopupHandler(adapter, runtime);
    // Test hook for the two-browser smoke (drop the socket like a network loss). No secrets exposed.
    (globalThis as Record<string, unknown>).__fazetimeDebug = {
      dropSocket: () => adapter.debugDropSocket(),
      status: () => adapter.status(),
      snapshotFetches: () => adapter.snapshotFetches,
      topup: () => adapter.peekTopUp(), // IDs and server status only; never the Checkout URL.
    };
    return;
  }
  const adapter = new MockBackend({
    latencyMs: 250,
    persistence: {
      load: () => storage.getItem<MockState>(MOCK_STATE_KEY),
      save: (state) => storage.setItem<MockState>(MOCK_STATE_KEY, state),
    },
  });
  attachRouter(adapter, runtime);
  attachPopupHandler(adapter, runtime);
});
