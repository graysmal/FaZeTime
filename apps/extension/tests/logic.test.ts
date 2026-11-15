import { describe, expect, it } from 'vitest';
import type { ErrorEnvelope, Pool, WagerReceiptResponse, WagerRequest } from '@fazetime/contracts';
import { checkStake, checkTopUp, estimateGrossReturn, formatMinor, minorToInput, parseDollarsToMinor } from '../src/lib/money';
import { formatCountdown, remainingMs, serverOffsetMs } from '../src/lib/time';
import { channelFromPath } from '../src/lib/route';
import { betReducer, IDLE, MAX_AUTO_ATTEMPTS, type BetFlow } from '../src/state/betFlow';
import { describeError } from '../src/state/errorCopy';
import { SNAPSHOT_FIXTURES } from '../src/mock/fixtures';

const pool = (yes: number, no: number): Pool => ({ yes_minor: yes, no_minor: no, total_minor: yes + no, simulated_minor: 0, wager_count: 0 });
const limits = SNAPSHOT_FIXTURES.open_no_position!.limits;

describe('estimate floor(s*(T+s)/(W_side+s)) (CONTRACTS 9.6)', () => {
  it('matches hand-computed values', () => {
    expect(estimateGrossReturn(500, pool(1500, 2500), 'YES')).toBe(1125); // 500*4500/2000
    expect(estimateGrossReturn(500, pool(1500, 2500), 'NO')).toBe(750); // 500*4500/3000
    expect(estimateGrossReturn(500, pool(0, 0), 'YES')).toBe(500); // empty pool: stake back
    expect(estimateGrossReturn(500, pool(1500, 0), 'NO')).toBe(2000); // 500*2000/500
  });
  it('floors exactly with integers, never floats', () => {
    // 300 * (1700 + 300) / (1000 + 300) = 600000 / 1300 = 461.53 -> 461
    expect(estimateGrossReturn(300, pool(1000, 700), 'YES')).toBe(Math.floor((300 * 2000) / 1300));
    // Large values stay exact (BigInt path).
    expect(estimateGrossReturn(50000, pool(400_000_000, 600_000_000), 'NO')).toBe(Number((50000n * 1_000_050_000n) / 600_050_000n));
  });
  it('is zero for invalid stakes', () => {
    expect(estimateGrossReturn(0, pool(1, 1), 'YES')).toBe(0);
    expect(estimateGrossReturn(1.5, pool(1, 1), 'YES')).toBe(0);
  });
});

describe('money parsing and limits from snapshot.limits', () => {
  it('parses dollars into integer cents without floats', () => {
    expect(parseDollarsToMinor('5')).toBe(500);
    expect(parseDollarsToMinor('$5.5')).toBe(550);
    expect(parseDollarsToMinor('0.07')).toBe(7);
    expect(parseDollarsToMinor('1,000')).toBe(100000);
    for (const bad of ['', 'abc', '-5', '5.001', '1e3']) expect(parseDollarsToMinor(bad)).toBeNull();
    expect(formatMinor(123405)).toBe('$1,234.05');
    expect(minorToInput(550)).toBe('5.50');
  });
  it('validates stakes and top-ups against the published limits', () => {
    expect(checkStake(500, limits)).toBeNull();
    expect(checkStake(50, limits)).toBe('BELOW_MIN');
    expect(checkStake(50_100, limits)).toBe('ABOVE_MAX');
    expect(checkStake(550, limits)).toBe('OFF_STEP');
    for (const p of [500, 1000, 5000]) expect(checkTopUp(p, limits)).toBeNull();
    expect(checkTopUp(400, limits)).toBe('BELOW_MIN');
    expect(checkTopUp(10_100, limits)).toBe('ABOVE_MAX');
    expect(checkTopUp(2550, limits)).toBe('OFF_STEP');
    expect(checkTopUp(2500, limits)).toBeNull();
  });
});

describe('server-time offset countdown (display only)', () => {
  it('uses the server clock, not the local one', () => {
    const local = Date.parse('2026-11-14T20:00:00.000Z');
    const offset = serverOffsetMs('2026-11-14T20:00:05.000Z', local); // server 5 s ahead
    expect(offset).toBe(5000);
    expect(remainingMs('2026-11-14T20:02:00.000Z', local, offset)).toBe(115_000);
    expect(formatCountdown(115_000)).toBe('1:55');
    expect(formatCountdown(400)).toBe('0:01');
    expect(formatCountdown(-10)).toBe('0:00');
    expect(formatCountdown(3_723_000)).toBe('1:02:03');
  });
});

describe('Twitch routes', () => {
  it('only plain channel pages get the panel', () => {
    expect(channelFromPath('/fazetime_demo')).toBe('fazetime_demo');
    expect(channelFromPath('/SomeChannel/')).toBe('somechannel');
    for (const p of ['/', '/directory', '/settings', '/videos', '/somechannel/videos', '/popout/x/chat', '/moderator/x', '/a-b'])
      expect(channelFromPath(p)).toBeNull();
  });
});

describe('bet flow reducer', () => {
  const req: WagerRequest = {
    operation_id: '11111111-1111-4111-8111-111111111111',
    stream_session_id: 'run_00000000000000000000000000000001',
    market_id: 'mkt_00000000000000000000000000000101',
    rules_version: 1,
    side: 'YES',
    amount_minor: 500,
  };
  const receipt = { ...(SNAPSHOT_FIXTURES.open_with_position!.my_position!.wagers[0] as object), schema_version: 1, operation_id: req.operation_id } as WagerReceiptResponse;
  const httpErr = (code: string, retryable = false, retry_after_ms: number | null = null) => ({
    ok: false as const,
    kind: 'http' as const,
    status: 409,
    error: { schema_version: 1, server_time_utc: '2026-11-14T20:00:00.000Z', error: { code, message: 'x', retryable, retry_after_ms, request_id: 'req_00000000000000000000000000000001', operation_id: req.operation_id, details: null } } as ErrorEnvelope,
  });

  it('shows success only after a receipt for the same operation_id', () => {
    let s: BetFlow = betReducer(IDLE, { type: 'SUBMIT', request: req });
    expect(s.kind).toBe('submitting');
    s = betReducer(s, { type: 'RESULT', operationId: 'other', result: { ok: true, status: 201, body: receipt } });
    expect(s.kind).toBe('submitting');
    s = betReducer(s, { type: 'RESULT', operationId: req.operation_id, result: { ok: true, status: 201, body: receipt } });
    expect(s.kind).toBe('accepted');
  });

  it('never allows a second submit while one is in flight or unknown', () => {
    const s1 = betReducer(IDLE, { type: 'SUBMIT', request: req });
    expect(betReducer(s1, { type: 'SUBMIT', request: { ...req, operation_id: '22222222-2222-4222-8222-222222222222' } })).toBe(s1);
    const s2 = betReducer(s1, { type: 'RESULT', operationId: req.operation_id, result: { ok: false, kind: 'unknown', message: 'timeout' } });
    expect(s2.kind).toBe('unknown');
    expect(betReducer(s2, { type: 'SUBMIT', request: req })).toBe(s2);
    expect(betReducer(s2, { type: 'DISMISS' })).toBe(s2);
  });

  it('unknown outcomes retry the SAME request; retryable errors honour retry_after_ms', () => {
    let s = betReducer(IDLE, { type: 'SUBMIT', request: req });
    s = betReducer(s, { type: 'RESULT', operationId: req.operation_id, result: httpErr('RATE_LIMITED', true, 2000) });
    expect(s).toMatchObject({ kind: 'unknown', retryInMs: 2000 });
    s = betReducer(s, { type: 'RETRY' });
    expect(s).toMatchObject({ kind: 'submitting', pending: { attempts: 2, request: req } });
    for (let i = 2; i < MAX_AUTO_ATTEMPTS; i++) {
      s = betReducer(s, { type: 'RESULT', operationId: req.operation_id, result: { ok: false, kind: 'unknown', message: 'x' } });
      s = betReducer(s, { type: 'RETRY' });
    }
    s = betReducer(s, { type: 'RESULT', operationId: req.operation_id, result: { ok: false, kind: 'unknown', message: 'x' } });
    expect(s).toMatchObject({ kind: 'unknown', retryInMs: null }); // Manual "check status" from here.
  });

  it('definitive typed errors are rejections, with copy per code', () => {
    const s = betReducer(betReducer(IDLE, { type: 'SUBMIT', request: req }), {
      type: 'RESULT',
      operationId: req.operation_id,
      result: httpErr('SIDE_CONFLICT'),
    });
    expect(s.kind).toBe('rejected');
    if (s.kind === 'rejected') expect(describeError({ ...s.error, details: { existing_side: 'YES' } }, () => 'RedFox').detail).toContain('RedFox');
    expect(describeError({ ...httpErr('INSUFFICIENT_FUNDS').error.error, details: { available_minor: 300, requested_minor: 500 } }).action).toBe('OPEN_TOPUP');
  });
});

describe('diamond glaze on hover', () => {
  it('glazes a button once when the pointer enters it, not when moving inside it, and never for touch', async () => {
    const { glazeOnHover } = await import('../src/ui/theme');
    document.body.innerHTML = '<button id="b"><span id="s">Wallet</span></button><div id="out"></div>';
    const b = document.getElementById('b')!;
    const s = document.getElementById('s')!;
    const out = document.getElementById('out')!;
    glazeOnHover({ target: s, relatedTarget: out, pointerType: 'mouse' });
    expect(b.classList.contains('ft-glaze')).toBe(true);
    b.classList.remove('ft-glaze');
    glazeOnHover({ target: b, relatedTarget: s, pointerType: 'mouse' }); // moving within the same button
    expect(b.classList.contains('ft-glaze')).toBe(false);
    glazeOnHover({ target: b, relatedTarget: out, pointerType: 'touch' });
    expect(b.classList.contains('ft-glaze')).toBe(false);
  });
});

describe('Θ display currency and wording (owner request 2026-11-15)', () => {
  it('shows drachmas at 1:1 only when switched, and still parses either symbol to the same cents', async () => {
    const { formatMinor, parseDollarsToMinor, setDisplayCurrency, currencySymbol } = await import('../src/lib/money');
    try {
      expect(formatMinor(2000)).toBe('$20.00');
      setDisplayCurrency('DRACHMA');
      expect(currencySymbol()).toBe('₯');
      expect(formatMinor(2000)).toBe('₯20.00');
      expect(formatMinor(-150)).toBe('-₯1.50');
      expect(parseDollarsToMinor('₯12.50')).toBe(1250);
      expect(parseDollarsToMinor('$12.50')).toBe(1250);
    } finally {
      setDisplayCurrency('USD');
    }
    expect(formatMinor(2000)).toBe('$20.00');
  });

  it('calls the AI "the Oracle" only in the Odyssey theme', async () => {
    const { aiName, setOracleFlavour } = await import('../src/ui/OdysseyDecor');
    expect(aiName()).toBe('AI');
    setOracleFlavour(true);
    expect(aiName()).toBe('The Oracle');
    setOracleFlavour(false);
    expect(aiName()).toBe('AI');
  });
});
