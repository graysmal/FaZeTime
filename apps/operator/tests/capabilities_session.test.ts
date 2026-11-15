import { afterEach, describe, expect, it } from 'vitest';
import { parseCapabilities } from '../src/api/capabilities';
import { SESSION_STORAGE_KEY, clearSession, loadSession, saveSession } from '../src/api/session';
import { TOKEN } from './helpers';

describe('parseCapabilities', () => {
  it('detects the §9.16 evidence routes and a $ref settle reason field', () => {
    const caps = parseCapabilities({
      paths: {
        '/v1/operator/evidence': { get: {} },
        '/v1/operator/evidence/{evidence_id}': { get: {} },
        '/v1/operator/markets/{market_id}/settle': {
          post: { requestBody: { content: { 'application/json': { schema: { $ref: '#/components/schemas/OpSettleMarket' } } } } },
        },
        '/v1/operator/ai-mode': { post: {} },
        '/v1/operator/candidates': { get: {} },
      },
      components: { schemas: { OpSettleMarket: { properties: { operation_id: {}, winning_side: {}, note: {} } } } },
    });
    expect(caps.evidenceList).toBe(true);
    expect(caps.evidenceImage).toBe(true);
    expect(caps.settleReasonField).toBe('note');
    expect(caps.aiModeRoute).toBe('/v1/operator/ai-mode');
    expect(caps.candidateRoutes).toEqual(['/v1/operator/candidates']);
  });

  it('reports absent routes as unavailable and tolerates junk', () => {
    const caps = parseCapabilities({ paths: { '/v1/operator/health': { get: {} } } });
    expect(caps.evidenceList).toBe(false);
    expect(caps.settleReasonField).toBeNull();
    expect(caps.aiModeRoute).toBeNull();
    expect(parseCapabilities('not json').evidenceList).toBe(false);
    expect(parseCapabilities(null).operatorPaths).toEqual([]);
  });
});

describe('session storage', () => {
  afterEach(() => sessionStorage.clear());
  const session = {
    token: TOKEN,
    session_id: `ses_${'e'.repeat(32)}`,
    expires_at_utc: '2099-01-01T00:00:00.000Z',
    user_id: `usr_${'f'.repeat(32)}`,
    display_name: 'Op',
  };

  it('round-trips through sessionStorage only', () => {
    saveSession(session);
    expect(loadSession()).toEqual(session);
    expect(localStorage.length).toBe(0);
    clearSession();
    expect(loadSession()).toBeNull();
  });

  it('drops malformed or expired entries', () => {
    sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify({ ...session, token: 'not-a-token' }));
    expect(loadSession()).toBeNull();
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify({ ...session, expires_at_utc: '2000-01-01T00:00:00.000Z' }));
    expect(loadSession()).toBeNull();
    expect(() => saveSession({ ...session, token: 'bad' })).toThrow();
  });
});
