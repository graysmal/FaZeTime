// Client IDs: canonical lowercase UUID from crypto.randomUUID() (CONTRACTS 9.1).
export function newOperationId(): string {
  return crypto.randomUUID().toLowerCase();
}

/** 32 lowercase hex chars from a CSPRNG (mock server IDs only). */
export function randomHex32(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}
