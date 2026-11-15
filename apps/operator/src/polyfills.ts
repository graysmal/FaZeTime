// The console is served over plain http://fazetime:8000 on the tailnet, which is NOT a secure context,
// so browsers do not expose crypto.randomUUID() there (it is SecureContext-only). crypto.getRandomValues()
// IS available in insecure contexts, so provide an RFC 4122 v4 fallback before any app code runs.
const c = globalThis.crypto as Crypto & { randomUUID?: () => string };
if (c && typeof c.randomUUID !== 'function' && typeof c.getRandomValues === 'function') {
  Object.defineProperty(c, 'randomUUID', {
    configurable: true,
    writable: true,
    value: (): string => {
      const b = c.getRandomValues(new Uint8Array(16));
      b[6] = (b[6] & 0x0f) | 0x40; // version 4
      b[8] = (b[8] & 0x3f) | 0x80; // RFC 4122 variant
      const h = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
      return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
    },
  });
}

export {};
