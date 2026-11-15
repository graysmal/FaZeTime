// Background-only persistence for the live adapter. Imported ONLY by entrypoints/background.ts.
// The session token lives in extension storage.local (accepted by the coordinator) under a key that
// content-script code never reads; it is never posted to tabs, put in URLs or logged.
import { storage } from 'wxt/utils/storage';
import type { JoinProfile, LiveStore, SessionRecord, TopUpRecord } from './backend';

const SESSION_KEY = 'local:fazetime.session.v1' as const;
const DEVICE_KEY = 'local:fazetime.deviceId' as const;
// P6: the tracked Stripe test top-up (IDs, amount, server status). Never the Checkout URL or a token.
const TOPUP_KEY = 'local:fazetime.topup.v1' as const;
// D35: the last accepted display name/label, for silent name-only re-join. Not a secret; cleared on sign-out.
const JOIN_PROFILE_KEY = 'local:fazetime.joinProfile.v1' as const;

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
  getTopUp: () => storage.getItem<TopUpRecord>(TOPUP_KEY),
  setTopUp: (record) => (record ? storage.setItem<TopUpRecord>(TOPUP_KEY, record) : storage.removeItem(TOPUP_KEY)),
  getJoinProfile: () => storage.getItem<JoinProfile>(JOIN_PROFILE_KEY),
  setJoinProfile: (profile) => (profile ? storage.setItem<JoinProfile>(JOIN_PROFILE_KEY, profile) : storage.removeItem(JOIN_PROFILE_KEY)),
};
