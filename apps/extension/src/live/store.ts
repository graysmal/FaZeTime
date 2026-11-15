// Background-only persistence for the live adapter. Imported ONLY by entrypoints/background.ts.
// The session token lives in extension storage.local (accepted by the coordinator) under a key that
// content-script code never reads; it is never posted to tabs, put in URLs or logged.
import { storage } from 'wxt/utils/storage';
import type { LiveStore, SessionRecord } from './backend';

const SESSION_KEY = 'local:fazetime.session.v1' as const;
const DEVICE_KEY = 'local:fazetime.deviceId' as const;

export const wxtLiveStore: LiveStore = {
  getSession: () => storage.getItem<SessionRecord>(SESSION_KEY),
  setSession: (session) => (session ? storage.setItem<SessionRecord>(SESSION_KEY, session) : storage.removeItem(SESSION_KEY)),
  async getDeviceId() {
    const existing = await storage.getItem<string>(DEVICE_KEY);
    if (existing) return existing;
    const id = crypto.randomUUID().toLowerCase();
    await storage.setItem(DEVICE_KEY, id);
    return id;
  },
};
