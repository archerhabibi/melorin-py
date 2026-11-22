// @melorin/api-client — thin, runtime-dependency-free client for Core `/api/v1`.
// Types come from the generated `schema.d.ts` (openapi-typescript); this file only moves bytes.
// Channels must keep pricing/wallet/order/payment/provisioning logic in Core and call it through here.

/** Replace `{name}` placeholders with URL-encoded values; throws when one is missing. */
/**
 * @param {string} template
 * @param {Record<string, any>} [params]
 */
export function buildPath(template, params = {}) {
  return template.replace(/\{([^}]+)\}/g, (/** @type {string} */ _, /** @type {string} */ name) => {
    const value = params[name];
    if (value === undefined || value === null) throw new Error(`Missing path parameter: ${name}`);
    return encodeURIComponent(String(value));
  });
}

/** Serialise a query object; skips null/undefined and repeats keys for arrays. */
/** @param {Record<string, any>} [query] */
export function buildQuery(query = {}) {
  const sp = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null) continue;
    for (const item of Array.isArray(value) ? value : [value]) sp.append(key, String(item));
  }
  const text = sp.toString();
  return text ? `?${text}` : '';
}

/**
 * @param {object} options
 * @param {string} [options.baseUrl]            API origin, no trailing slash needed.
 * @param {() => (string|null|undefined)} [options.getAccessToken]  In-memory bearer token provider.
 * @param {() => Promise<boolean>} [options.refresh]  Called once on 401; return true to retry the request.
 * @param {typeof fetch} [options.fetch]        Custom fetch (tests, SSR).
 * @param {RequestCredentials} [options.credentials]
 */
export function createApiClient({
  baseUrl = '',
  getAccessToken,
  refresh,
  fetch: fetchImpl,
  credentials = 'include',
} = {}) {
  const root = String(baseUrl).replace(/\/$/, '');

  /**
   * @param {string} method
   * @param {string} path
   * @param {{ params?: { path?: Record<string, any>, query?: Record<string, any> }, body?: any, headers?: Record<string, string>, signal?: AbortSignal }} [init]
   */
  async function request(method, path, init = {}) {
    const doFetch = fetchImpl || globalThis.fetch;
    const url = `${root}${buildPath(path, init.params?.path)}${buildQuery(init.params?.query)}`;
    const send = () => {
      const token = getAccessToken?.();
      const hasBody = init.body !== undefined && !(init.body instanceof FormData);
      return doFetch(url, {
        method: method.toUpperCase(),
        credentials,
        headers: {
          Accept: 'application/json',
          ...(hasBody ? { 'Content-Type': 'application/json' } : {}),
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          ...(init.headers || {}),
        },
        body: init.body === undefined ? undefined : hasBody ? JSON.stringify(init.body) : init.body,
        signal: init.signal,
      });
    };
    let response = await send();
    if (response.status === 401 && refresh && (await refresh())) response = await send();
    // Parse a CLONE: the caller keeps an unread `response`, so `errText(response)` / `response.json()` still work after a
    // failed call (an already-consumed body would silently turn every server message into the generic fallback).
    const text = response.status === 204 ? '' : await response.clone().text();
    let payload;
    try {
      payload = text ? JSON.parse(text) : undefined;
    } catch {
      payload = text;
    }
    return response.ok ? { data: payload, error: undefined, response } : { data: undefined, error: payload, response };
  }

  /**
   * Same transport rules as `request` (bearer token, one shared refresh on 401, cookies) but hands back the unread
   * `Response` and sends `init.body` verbatim (string/Blob/FormData). For views that stream or pre-serialise their body
   * and for the generic `call(path, init)` helper; typed endpoints should use `get/post/...` instead.
   * @param {string} path  Already-built path (query included).
   * @param {RequestInit} [init]
   * @returns {Promise<Response>}
   */
  async function raw(path, init = {}) {
    const doFetch = fetchImpl || globalThis.fetch;
    const send = () => {
      const token = getAccessToken?.();
      const body = init.body;
      return doFetch(`${root}${path}`, {
        ...init,
        credentials,
        headers: {
          Accept: 'application/json',
          ...(body && !(body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
          ...(init.headers || {}),
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });
    };
    let response = await send();
    if (response.status === 401 && refresh && (await refresh())) response = await send();
    return response;
  }

  return {
    request,
    raw,
    /** @param {string} path @param {{ params?: { path?: Record<string, any>, query?: Record<string, any> }, headers?: Record<string, string>, signal?: AbortSignal }} [init] */
    // async on purpose: a missing path parameter must surface as a rejected promise, like every other failure
    rawGet: async (path, init = {}) =>
      raw(`${buildPath(path, init.params?.path)}${buildQuery(init.params?.query)}`, {
        method: 'GET',
        headers: { Accept: '*/*', ...(init.headers || {}) },
        signal: init.signal,
      }),
    /** @param {string} path @param {Parameters<typeof request>[2]} [init] */
    get: (path, init) => request('get', path, init),
    /** @param {string} path @param {Parameters<typeof request>[2]} [init] */
    post: (path, init) => request('post', path, init),
    /** @param {string} path @param {Parameters<typeof request>[2]} [init] */
    put: (path, init) => request('put', path, init),
    /** @param {string} path @param {Parameters<typeof request>[2]} [init] */
    patch: (path, init) => request('patch', path, init),
    /** @param {string} path @param {Parameters<typeof request>[2]} [init] */
    delete: (path, init) => request('delete', path, init),
  };
}
