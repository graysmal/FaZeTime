// Extension-storage adapter for UI preferences, the profile label and the pending wager record.
// Everything here is non-secret. P2 note: the session token must live ONLY in background-owned
// storage.session (trusted contexts by default) and never be read by content scripts or the page.
import { storage, type StorageItemKey } from 'wxt/utils/storage';
import type { KV } from './state/controller';

const asKey = (key: string) => key as StorageItemKey;

export const wxtKV: KV = {
  get: <T,>(key: string) => storage.getItem<T>(asKey(key)),
  set: <T,>(key: string, value: T) => storage.setItem<T>(asKey(key), value),
  remove: (key: string) => storage.removeItem(asKey(key)),
};

export function watchKey<T>(key: string, cb: (value: T | null) => void): () => void {
  return storage.watch<T>(asKey(key), (value) => cb(value ?? null));
}
