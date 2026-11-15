// Server-time offset and display countdown. Display only: the server decides acceptance
// (`close_at_utc` is exclusive and checked at commit time, CONTRACTS 9.3).

/** Offset to add to the local clock to estimate server time. */
export function serverOffsetMs(serverTimeUtc: string, receivedAtLocalMs: number): number {
  const server = Date.parse(serverTimeUtc);
  return Number.isNaN(server) ? 0 : server - receivedAtLocalMs;
}

export function remainingMs(closeAtUtc: string, nowLocalMs: number, offsetMs: number): number {
  const close = Date.parse(closeAtUtc);
  if (Number.isNaN(close)) return 0;
  return close - (nowLocalMs + offsetMs);
}

/** "2:00", "0:09", "1:02:03"; clamps at 0:00. Rounds up so 0:00 shows only once closed. */
export function formatCountdown(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const ss = s.toString().padStart(2, '0');
  return h > 0 ? `${h}:${m.toString().padStart(2, '0')}:${ss}` : `${m}:${ss}`;
}
