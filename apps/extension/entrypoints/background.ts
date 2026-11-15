// Background service worker. It owns the backend adapter: every API call (P1 MOCK now, P2 live)
// happens here, never in a content script (coordinator note: extension origin avoids mixed-content,
// page CORS and local-network-access prompts). Memory here is disposable; the MOCK state is
// persisted to storage.session and content scripts resync from snapshots on reconnect.
import { browser } from 'wxt/browser';
import { defineBackground } from 'wxt/utils/define-background';
import { storage } from 'wxt/utils/storage';
import { attachRouter, type RuntimeLike } from '../src/api/router';
import { MockBackend, type MockState } from '../src/mock/backend';

const MOCK_STATE_KEY = 'session:fazetime.mockState';

export default defineBackground(() => {
  const adapter = new MockBackend({
    latencyMs: 250,
    persistence: {
      load: () => storage.getItem<MockState>(MOCK_STATE_KEY),
      save: (state) => storage.setItem<MockState>(MOCK_STATE_KEY, state),
    },
  });
  attachRouter(adapter, browser.runtime as unknown as RuntimeLike);
});
