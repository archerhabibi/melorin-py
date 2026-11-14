import { createApiClient } from '@melorin/api-client';
import type { PathsWith } from '@melorin/api-client';
import { getAccessToken, setTokens, clearTokens } from './auth.ts';
import type { Json } from './types.ts';

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

/** fetch with in-memory bearer token and a single transparent refresh on 401. */
export async function authFetch(base: string, path: string, options: RequestInit = {}): Promise<Response> {
  const build = () => ({
    ...options,
    headers: {
      Accept: 'application/json',
      ...(options.body && !(options.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
      ...((options.headers as Record<string, string>) || {}),
      ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {}),
    },
  });
  let r = await fetch(`${base}${path}`, { ...build(), credentials: 'include' });
  if (r.status === 401 && (await refreshPair(base))) r = await fetch(`${base}${path}`, build());
  return r;
}

/**
 * Typed client on the SAME transport rules as authFetch (in-memory bearer token, one shared refresh on 401).
 * Prefer this for endpoints present in the OpenAPI snapshot: path, params and body are checked at compile time.
 * `result.response` is the raw Response (use it with errText); `result.data` is typed from the schema.
 */
export const typedClient = (base: string) =>
  createApiClient({ baseUrl: base, getAccessToken, refresh: () => refreshPair(base) });

/** GET + parse JSON through @melorin/api-client (T15): bearer token, one transparent refresh on 401. */
export async function getJson<T = Json>(base: string, path: string): Promise<T> {
  const client = createApiClient({ baseUrl: base, getAccessToken, refresh: () => refreshPair(base) });
  const { data, response } = await client.get(path as PathsWith<'get'>);
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return data as T;
}
