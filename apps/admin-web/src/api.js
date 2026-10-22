import { getAccessToken, setTokens, clearTokens } from "./auth.js";

export const API_BASE = (import.meta.env?.VITE_MELORIN_API_URL || window.location.origin).replace(/\/$/, "");

let refreshing = null;
async function refreshPair(base) {
  if (!refreshing) {
    refreshing = fetch(`${base}/api/v1/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: "{}",
    })
      .then(async (r) => {
        if (!r.ok) { clearTokens(); return false; }
        setTokens(await r.json());
        return true;
      })
      .catch(() => false)
      .finally(() => { refreshing = null; });
  }
  return refreshing;
}

/** fetch with in-memory bearer token and a single transparent refresh on 401. */
export async function authFetch(base, path, options = {}) {
  const build = () => ({
    ...options,
    headers: {
      Accept: "application/json",
      ...(options.body && !(options.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
      ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {}),
    },
  });
  let r = await fetch(`${base}${path}`, {...build(), credentials: "include"});
  if (r.status === 401 && (await refreshPair(base))) r = await fetch(`${base}${path}`, build());
  return r;
}

export async function getJson(base, path) {
  const r = await authFetch(base, path);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}
