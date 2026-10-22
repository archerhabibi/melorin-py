import { beforeEach, describe, expect, it, vi } from 'vitest';
import { clearTokens, getAccessToken, setTokens } from '../src/auth.js';
import { authFetch, getJson } from '../src/api.js';

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const BASE = 'https://api.test';

describe('authFetch', () => {
  let fetchMock;
  beforeEach(() => {
    clearTokens();
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  it('sends the in-memory bearer token and always includes cookies on the first attempt', async () => {
    setTokens({ access_token: 'tok-1' });
    fetchMock.mockResolvedValueOnce(json({ ok: true }));
    await authFetch(BASE, '/api/v1/me');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/api/v1/me`);
    expect(init.headers.Authorization).toBe('Bearer tok-1');
    expect(init.headers.Accept).toBe('application/json');
    expect(init.credentials).toBe('include');
  });

  it('sends no Authorization header when signed out', async () => {
    fetchMock.mockResolvedValueOnce(json({}));
    await authFetch(BASE, '/x');
    expect(fetchMock.mock.calls[0][1].headers).not.toHaveProperty('Authorization');
  });

  it('sets a JSON content type for string bodies but leaves FormData to the browser', async () => {
    fetchMock.mockResolvedValue(json({}));
    await authFetch(BASE, '/x', { method: 'POST', body: '{"a":1}' });
    expect(fetchMock.mock.calls[0][1].headers['Content-Type']).toBe('application/json');
    await authFetch(BASE, '/x', { method: 'POST', body: new FormData() });
    expect(fetchMock.mock.calls[1][1].headers).not.toHaveProperty('Content-Type');
    await authFetch(BASE, '/x');
    expect(fetchMock.mock.calls[2][1].headers).not.toHaveProperty('Content-Type');
  });

  it('refreshes once on 401, stores the new token and retries the original request with it', async () => {
    setTokens({ access_token: 'old' });
    fetchMock
      .mockResolvedValueOnce(json({}, 401))
      .mockResolvedValueOnce(json({ access_token: 'new' }))
      .mockResolvedValueOnce(json({ ok: 1 }));
    const r = await authFetch(BASE, '/api/v1/admin/x');
    expect(r.status).toBe(200);
    expect(fetchMock.mock.calls[1][0]).toBe(`${BASE}/api/v1/auth/refresh`);
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: 'POST', credentials: 'include' });
    expect(fetchMock.mock.calls[2][1].headers.Authorization).toBe('Bearer new');
    expect(getAccessToken()).toBe('new');
  });

  it('gives up and clears the session when the refresh is rejected (no retry loop)', async () => {
    setTokens({ access_token: 'old' });
    fetchMock.mockResolvedValueOnce(json({}, 401)).mockResolvedValueOnce(json({}, 401));
    const r = await authFetch(BASE, '/api/v1/admin/x');
    expect(r.status).toBe(401);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(getAccessToken()).toBe('');
  });

  it('treats a network failure during refresh as a failed refresh', async () => {
    setTokens({ access_token: 'old' });
    fetchMock.mockResolvedValueOnce(json({}, 401)).mockRejectedValueOnce(new TypeError('offline'));
    const r = await authFetch(BASE, '/x');
    expect(r.status).toBe(401);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('shares one refresh between concurrent 401s (a burst must not burn several refresh tokens)', async () => {
    setTokens({ access_token: 'old' });
    let refreshCalls = 0;
    fetchMock.mockImplementation(async (url, init) => {
      if (String(url).endsWith('/auth/refresh')) {
        refreshCalls += 1;
        return json({ access_token: 'fresh' });
      }
      return init.headers.Authorization === 'Bearer fresh' ? json({ ok: 1 }) : json({}, 401);
    });
    const results = await Promise.all([authFetch(BASE, '/a'), authFetch(BASE, '/b'), authFetch(BASE, '/c')]);
    expect(results.map((r) => r.status)).toEqual([200, 200, 200]);
    expect(refreshCalls).toBe(1);
  });

  it('does not try to refresh for non-401 errors', async () => {
    fetchMock.mockResolvedValueOnce(json({}, 500));
    expect((await authFetch(BASE, '/x')).status).toBe(500);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe('getJson', () => {
  beforeEach(() => {
    clearTokens();
    vi.stubGlobal('fetch', vi.fn());
  });

  it('returns the parsed body on success', async () => {
    fetch.mockResolvedValueOnce(json({ items: [1] }));
    await expect(getJson(BASE, '/ok')).resolves.toEqual({ items: [1] });
  });

  it('throws with the path and status on a failure so screens can show an error state', async () => {
    fetch.mockResolvedValueOnce(json({}, 403));
    await expect(getJson(BASE, '/denied')).rejects.toThrow('/denied: 403');
  });
});
