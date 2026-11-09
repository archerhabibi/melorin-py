// Anonymous (no bearer token) reads of the public storefront API, through @melorin/api-client (T15).
import { createApiClient } from '@melorin/api-client';

const base = (import.meta.env?.VITE_MELORIN_API_URL || window.location.origin).replace(/\/$/, '');
// 'same-origin' keeps the exact credential behaviour the previous plain fetch() calls had.
const publicApi = createApiClient({ baseUrl: base, credentials: 'same-origin' });

/** GET → parsed JSON; rejects with Error(<status>) on a non-2xx answer (same contract as the old `r.ok ? r.json() : reject`). */
export async function publicGet(path) {
  const { data, response } = await publicApi.get(path);
  if (!response.ok) throw new Error(String(response.status));
  return data;
}
/** Like publicGet but resolves null instead of rejecting on a non-2xx answer. */
export async function publicGetOrNull(path) {
  const { data, response } = await publicApi.get(path);
  return response.ok ? data : null;
}
