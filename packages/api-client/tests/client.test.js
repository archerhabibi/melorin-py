import assert from 'node:assert/strict';
import test from 'node:test';
import { buildPath, buildQuery, createApiClient } from '../src/index.js';

const reply = (status, body) => new Response(body === undefined ? null : JSON.stringify(body), { status });

test('buildPath encodes and rejects missing params', () => {
  assert.equal(buildPath('/api/v1/x/{id}', { id: 'a b/c' }), '/api/v1/x/a%20b%2Fc');
  assert.throws(() => buildPath('/api/v1/x/{id}', {}), /Missing path parameter: id/);
});

test('buildQuery skips empty values and repeats arrays', () => {
  assert.equal(buildQuery({ a: 1, b: undefined, c: null, d: ['x', 'y'] }), '?a=1&d=x&d=y');
  assert.equal(buildQuery(), '');
});

test('get sends bearer token and parses JSON', async () => {
  const seen = [];
  const api = createApiClient({
    baseUrl: 'https://api.example.test/',
    getAccessToken: () => 'tok',
    fetch: async (url, init) => (seen.push({ url, init }), reply(200, { ok: true })),
  });
  const r = await api.request('get', '/health', { params: { query: { q: 'x' } } });
  assert.deepEqual(r.data, { ok: true });
  assert.equal(seen[0].url, 'https://api.example.test/health?q=x');
  assert.equal(seen[0].init.headers.Authorization, 'Bearer tok');
});

test('post serialises JSON body; errors surface as {error}', async () => {
  let body;
  const api = createApiClient({
    fetch: async (_url, init) => ((body = init.body), reply(422, { detail: 'bad' })),
  });
  const r = await api.post('/x', { body: { n: 1 } });
  assert.equal(body, '{"n":1}');
  assert.equal(r.data, undefined);
  assert.deepEqual(r.error, { detail: 'bad' });
});

test('401 triggers exactly one refresh + retry', async () => {
  let calls = 0;
  let refreshed = 0;
  let token = 'old';
  const api = createApiClient({
    getAccessToken: () => token,
    refresh: async () => ((refreshed += 1), (token = 'new'), true),
    fetch: async (_u, init) => (calls++, init.headers.Authorization === 'Bearer new' ? reply(200, { ok: 1 }) : reply(401, {})),
  });
  const r = await api.get('/me');
  assert.equal(calls, 2);
  assert.equal(refreshed, 1);
  assert.deepEqual(r.data, { ok: 1 });
});

test('204 yields undefined data', async () => {
  const api = createApiClient({ fetch: async () => reply(204) });
  const r = await api.delete('/x');
  assert.equal(r.data, undefined);
  assert.equal(r.error, undefined);
});

test('raw: bearer + one refresh on 401, body verbatim, unread Response back', async () => {
  const calls = [];
  let token = 'old';
  const fetch = async (url, init) => {
    calls.push([url, init]);
    return calls.length === 1 ? reply(401, {}) : reply(200, { ok: 1 });
  };
  const c = createApiClient({
    baseUrl: 'https://x.test/',
    fetch,
    getAccessToken: () => token,
    refresh: async () => ((token = 'new'), true),
  });
  const r = await c.raw('/a?b=1', { method: 'POST', body: '{"k":1}' });
  assert.equal(r.status, 200);
  assert.deepEqual(await r.json(), { ok: 1 });
  assert.equal(calls.length, 2);
  assert.equal(calls[0][0], 'https://x.test/a?b=1');
  assert.equal(calls[0][1].body, '{"k":1}');
  assert.equal(calls[0][1].headers['Content-Type'], 'application/json');
  assert.equal(calls[0][1].headers.Authorization, 'Bearer old');
  assert.equal(calls[1][1].headers.Authorization, 'Bearer new');
});


test('rawGet builds a schema-path URL, preserves binary response and auth refresh', async () => {
  const calls = [];
  let token = 'old';
  const binary = new Response(new Uint8Array([0, 1, 2]), { status: 200, headers: { 'Content-Type': 'image/png' } });
  const api = createApiClient({
    baseUrl: 'https://api.example.test',
    getAccessToken: () => token,
    refresh: async () => ((token = 'new'), true),
    fetch: async (url, init) => {
      calls.push({ url, init });
      return calls.length === 1 ? reply(401, {}) : binary;
    },
  });
  const response = await api.rawGet('/api/v1/admin/payments/{payment_id}/receipt', {
    params: { path: { payment_id: 'pay/1' } },
  });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('Content-Type'), 'image/png');
  assert.deepEqual([...new Uint8Array(await response.arrayBuffer())], [0, 1, 2]);
  assert.equal(calls.length, 2);
  assert.equal(calls[0].url, 'https://api.example.test/api/v1/admin/payments/pay%2F1/receipt');
  assert.equal(calls[0].init.method, 'GET');
  assert.equal(calls[0].init.headers.Accept, '*/*');
  assert.equal(calls[0].init.headers.Authorization, 'Bearer old');
  assert.equal(calls[1].init.headers.Authorization, 'Bearer new');
});

test('rawGet: query string, extra headers and a missing path parameter', async () => {
  const calls = [];
  const api = createApiClient({
    baseUrl: 'https://api.example.test/',
    fetch: async (url, init) => (calls.push({ url, init }), new Response('ok')),
  });
  await api.rawGet('/api/v1/admin/audit', { params: { query: { limit: 5, tag: ['a', 'b'], skip: undefined } }, headers: { Accept: 'text/csv' } });
  assert.equal(calls[0].url, 'https://api.example.test/api/v1/admin/audit?limit=5&tag=a&tag=b');
  assert.equal(calls[0].init.headers.Accept, 'text/csv');
  await assert.rejects(() => api.rawGet('/api/v1/admin/payments/{payment_id}/receipt', { params: { path: {} } }), /Missing path parameter: payment_id/);
  assert.equal(calls.length, 1);
});
