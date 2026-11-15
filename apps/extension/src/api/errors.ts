import {
  ERROR_HTTP_STATUS,
  RETRYABLE_ERROR_CODES,
  type ErrorCode,
  type ErrorEnvelope,
} from '@fazetime/contracts';
import { randomHex32 } from '../lib/ids';
import type { ApiResult } from './types';

export function errorEnvelope(
  code: ErrorCode,
  message: string,
  opts: { operation_id?: string | null; details?: Record<string, unknown> | null; retry_after_ms?: number | null; now?: number } = {},
): ErrorEnvelope {
  return {
    schema_version: 1,
    error: {
      code,
      message,
      retryable: (RETRYABLE_ERROR_CODES as readonly string[]).includes(code),
      retry_after_ms: opts.retry_after_ms ?? null,
      request_id: `req_${randomHex32()}`,
      operation_id: opts.operation_id ?? null,
      details: opts.details ?? null,
    },
    server_time_utc: new Date(opts.now ?? Date.now()).toISOString(),
  };
}

export function httpError<T>(code: ErrorCode, message: string, opts: Parameters<typeof errorEnvelope>[2] = {}): ApiResult<T> {
  return { ok: false, kind: 'http', status: ERROR_HTTP_STATUS[code], error: errorEnvelope(code, message, opts) };
}

export function unknownOutcome<T>(message: string): ApiResult<T> {
  return { ok: false, kind: 'unknown', message };
}
