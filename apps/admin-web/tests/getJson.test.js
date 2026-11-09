import { afterEach, describe, expect, it, vi } from 'vitest';
import { clearTokens, setTokens } from '../src/auth.js';
import { getJson } from '../src/api.js';

const reply = (status, body) => ({
  status,
  ok: status < 400,
  text: async () => JSON.stringify(body),
  json: async () => body,
});

afterEach(() => clearTokens());

describe('getJson (api-client consumer, T15)', () => {
  it('sends the bearer token and returns parsed JSON', async () => {
    setTokens({ access_token: 'tok' });
    const f = vi.fn().mockResolvedValue(reply(200, { ok: true }));
    vi.stubGlobal('fetch', f);
    await expect(getJson('http://core', '/api/v1/me')).resolves.toEqual({ ok: true });
    expect(f.mock.calls[0][0]).toBe('http://core/api/v1/me');
    expect(f.mock.calls[0][1].headers.Authorization).toBe('Bearer tok');
  });

  it('refreshes once on 401 and retries with the new token', async () => {
    setTokens({ access_token: 'old' });
    const f = vi
      .fn()
      .mockResolvedValueOnce(reply(401, {}))
      .mockResolvedValueOnce(reply(200, { access_token: 'new' })) // /auth/refresh
      .mockResolvedValueOnce(reply(200, { me: 1 }));
    vi.stubGlobal('fetch', f);
    await expect(getJson('http://core', '/api/v1/me')).resolves.toEqual({ me: 1 });
    expect(f.mock.calls[1][0]).toBe('http://core/api/v1/auth/refresh');
    expect(f.mock.calls[2][1].headers.Authorization).toBe('Bearer new');
  });

  it('throws "<path>: <status>" on failure (message unchanged)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply(500, {})));
    await expect(getJson('http://core', '/api/v1/x')).rejects.toThrow('/api/v1/x: 500');
  });
});
