import { describe, expect, it, vi } from 'vitest';
import { publicGet, publicGetOrNull } from '../src/coreApi.js';

const reply = (status, body) => ({ status, ok: status < 400, text: async () => JSON.stringify(body) });

describe('coreApi (api-client consumer, T15)', () => {
  it('publicGet returns parsed JSON and sends an Accept header without a bearer token', async () => {
    const f = vi.fn().mockResolvedValue(reply(200, [{ id: 1 }]));
    vi.stubGlobal('fetch', f);
    await expect(publicGet('/api/v1/stores/s1/bundles')).resolves.toEqual([{ id: 1 }]);
    const [url, init] = f.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/stores\/s1\/bundles$/);
    expect(init.method).toBe('GET');
    expect(init.credentials).toBe('same-origin');
    expect(init.headers.Authorization).toBeUndefined();
  });

  it('publicGet rejects with the HTTP status on a non-2xx answer', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply(503, { detail: 'down' })));
    await expect(publicGet('/x')).rejects.toThrow('503');
  });

  it('publicGetOrNull resolves null on a non-2xx answer', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply(404, {})));
    await expect(publicGetOrNull('/x')).resolves.toBeNull();
  });
});
