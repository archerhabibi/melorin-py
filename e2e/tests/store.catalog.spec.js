import { expect, test } from '@playwright/test';
import { failOnPageErrors, mockCore } from './helpers.js';

test('storefront shows the bundles served by Core for the main store', async ({ page }) => {
  const assertNoErrors = failOnPageErrors(page);
  await mockCore(page, {
    'GET /api/v1/auth/telegram/config': { enabled: false },
    'GET /api/v1/auth/google/config': { enabled: false },
    'GET /api/v1/stores/main': { id: 'store-main', bot_username: null },
    // The bundle picker is rendered only when the store sells more than one bundle (a single one is auto-selected).
    'GET /api/v1/stores/store-main/bundles': [
      { id: 'b1', name: 'E2E Bundle', mode: 'fixed' },
      { id: 'b2', name: 'E2E Second Bundle', mode: 'fixed' },
    ],
    'GET /api/v1/stores/store-main/bundles/b1/packages': [],
    'GET /api/v1/stores/store-main/bundles/b2/packages': [],
  });
  await page.goto('/');
  await expect(page).toHaveTitle(/ملورین/);
  await expect(page.getByRole('button', { name: 'E2E Bundle' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'E2E Second Bundle' })).toBeVisible();
  assertNoErrors();
});

test('storefront degrades gracefully when Core is down', async ({ page }) => {
  const assertNoErrors = failOnPageErrors(page);
  await mockCore(page, { 'GET /api/v1/stores/main': { status: 503, body: { detail: 'down' } } });
  await page.goto('/');
  await expect(page.getByText('Core در دسترس نیست').first()).toBeVisible();
  assertNoErrors();
});

// Purchase and payment need the real wallet/ledger; they are covered by scripts/e2e_smoke.py against staging.
test.fixme('signed-in customer buys a package from the wallet (needs seeded staging stack)', async () => {});
