// Minimal Core API double. Unmocked /api/ calls answer 404 so a spec never silently depends on a real backend.
export async function mockCore(page, handlers = {}) {
  const seen = [];
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    const key = `${route.request().method()} ${url.pathname}`;
    seen.push(key);
    const h = handlers[key];
    if (h === undefined)
      return route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"not mocked"}' });
    const { status = 200, body = {} } = typeof h === 'function' ? h(route.request()) : { body: h };
    return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  });
  return seen;
}

/** Fail the test on uncaught page errors (a white screen is the most common frontend regression). */
export function failOnPageErrors(page) {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  return () => {
    if (errors.length) throw new Error(`Uncaught page errors:\n${errors.join('\n')}`);
  };
}
