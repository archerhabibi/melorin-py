import { useMemo } from 'react';
import { createApiClient } from '@melorin/api-client';
import type { PathsWith } from '@melorin/api-client';
import { getAccessToken, setTokens, clearTokens } from './auth.ts';
import type { Json } from '../shared/types.ts';

export const API_BASE = (import.meta.env?.VITE_MELORIN_API_URL || window.location.origin).replace(/\/$/, '');

let refreshing: Json = null;
async function refreshPair(base: string) {
  if (!refreshing) {
    refreshing = fetch(`${base}/api/v1/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: '{}',
    })
      .then(async (r) => {
        if (!r.ok) {
          clearTokens();
          return false;
        }
        setTokens(await r.json());
        return true;
      })
      .catch(() => false)
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

/** fetch with in-memory bearer token and a single transparent refresh on 401 — implemented by @melorin/api-client (`raw`). */
export const authFetch = (base: string, path: string, options: RequestInit = {}): Promise<Response> =>
  typedClient(base).raw(path, options);

/**
 * Typed client on the SAME transport rules as authFetch (in-memory bearer token, one shared refresh on 401).
 * Prefer this for endpoints present in the OpenAPI snapshot: path, params and body are checked at compile time.
 * `result.response` is the raw Response (use it with errText); `result.data` is typed from the schema.
 */
export const typedClient = (base: string) =>
  createApiClient({ baseUrl: base, getAccessToken, refresh: () => refreshPair(base) });

/** Authenticated file download (CSV/Blob): the ONE place a view reaches a raw `Response` body; keeps the bearer + refresh rules. */
export async function downloadFile(base: string, path: string, filename: string): Promise<void> {
  const r = await authFetch(base, path, { headers: { Accept: '*/*' } });
  if (!r.ok) throw new Error(`export ${r.status}`);
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** GET + parse JSON through @melorin/api-client (T15): bearer token, one transparent refresh on 401. */
export async function getJson<T = Json>(base: string, path: string): Promise<T> {
  const client = createApiClient({ baseUrl: base, getAccessToken, refresh: () => refreshPair(base) });
  const { data, response } = await client.get(path as PathsWith<'get'>);
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return data as T;
}

/** Typed-client result -> the raw Response plus the parsed body (data on success, error body otherwise; {} when empty). */
export const settled = (res: { response: Response; data?: unknown; error?: unknown }) => ({
  r: res.response,
  d: ((res.response.ok ? res.data : res.error) ?? {}) as Record<string, unknown> & Json,
});

/**
 * Stable `(path, init) => Response` bound to the API base, for screens that feed a generic path to shared helpers (useRows, web-kit hooks).
 * The ONE place views reach `authFetch`; endpoints with a literal path should use `typedClient` instead (see the ratchet test).
 */
export const useCall = (api?: { base?: string } | null) => {
  const base = api?.base ?? '';
  return useMemo(
    () =>
      (p: string, o: RequestInit = {}) =>
        authFetch(base, p, o),
    [base],
  );
};
