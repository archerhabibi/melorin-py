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
    const text = response.status === 204 ? '' : await response.text();
    let payload;
    try {
      payload = text ? JSON.parse(text) : undefined;
    } catch {
      payload = text;
    }
    return response.ok ? { data: payload, error: undefined, response } : { data: undefined, error: payload, response };
  }

  return {
    request,
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
