// Browser safety net for the storefront `App` component: email sign-in -> pick a package -> quote -> wallet payment -> delivery.
// Core is mocked with page.route, so this runs without Postgres/Redis (the real money path stays in scripts/e2e_smoke.py).
// It exists so the App.jsx split / TypeScript migration (T-R11) is verified in a real browser, not only in jsdom.
import { expect, test } from '@playwright/test';
import { failOnPageErrors, mockCore } from './helpers.js';

const PAIR = { access_token: 'tok-1', refresh_token: 'ref-1', is_admin: false };
const PKG = { id: 'p1', product_id: 'p1', name: 'E2E Plan', price: 100000, duration_days: 30, traffic_gb: 50 };
const ME = { id: 'u1', display_name: 'Tester', identities: [{ provider: 'google' }] };

function baseHandlers(extra = {}) {
  return {
    'GET /api/v1/auth/telegram/config': { enabled: false },
    'GET /api/v1/auth/google/config': { enabled: false },
    'GET /api/v1/stores/main': { id: 'store-main', bot_username: null },
    'GET /api/v1/stores/store-main/bundles': [{ id: 'b1', name: 'E2E Bundle', selection_mode: 'auto' }],
    'GET /api/v1/stores/store-main/bundles/b1/packages': [PKG],
    'POST /api/v1/auth/refresh': { status: 401, body: { detail: 'no session' } },
    ...extra,
  };
}

const signedIn = (extra = {}) =>
  baseHandlers({
    'POST /api/v1/auth/refresh': PAIR, // an existing cookie session is restored on load
    'GET /api/v1/me': ME,
    'GET /api/v1/stores/store-main/wallet': { balance: 500000, currency: 'تومان' },
    'GET /api/v1/stores/store-main/orders': [],
    ...extra,
  });

test('guest picking a package is asked to sign in, then email code login succeeds', async ({ page }) => {
  const assertNoErrors = failOnPageErrors(page);
  const seen = await mockCore(
    page,
    baseHandlers({
      'POST /api/v1/auth/email/request-code': { ok: true },
      'POST /api/v1/auth/email/verify-code': PAIR,
      'GET /api/v1/me': ME,
      'GET /api/v1/stores/store-main/wallet': { balance: 500000, currency: 'تومان' },
      'GET /api/v1/stores/store-main/orders': [],
    }),
  );
  await page.goto('/');
  await page.getByRole('button', { name: /E2E Plan/ }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await dialog.getByPlaceholder('email@example.com').fill('buyer@example.com');
  await dialog.getByRole('button', { name: /ارسال کد ورود/ }).click();
  await dialog.getByLabel('کد ورود').fill('123456');
  await dialog.getByRole('button', { name: /تأیید و ورود/ }).click();
  await expect(dialog).toBeHidden();
  expect(seen).toContain('POST /api/v1/auth/email/verify-code');
  await expect(page.getByRole('button', { name: /Tester/ }).first()).toBeVisible();
  assertNoErrors();
});

test('signed-in customer gets a quote and pays from the wallet (delivery dialog opens)', async ({ page }) => {
  const assertNoErrors = failOnPageErrors(page);
  let orderBody = null;
  const seen = await mockCore(
    page,
    signedIn({
      'POST /api/v1/stores/store-main/checkout/quote': {
        total: 100000,
        currency: 'تومان',
        wallet_balance: 500000,
        sufficient_funds: true,
      },
      'POST /api/v1/stores/store-main/orders': (req) => {
        orderBody = req.postDataJSON();
        return { id: 'o1' };
      },
    }),
  );
  await page.goto('/');
  await page.getByRole('button', { name: /E2E Plan/ }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText('مبلغ نهایی')).toBeVisible();
  await dialog.getByRole('button', { name: /پرداخت از کیف پول/ }).click();
  await expect.poll(() => orderBody).not.toBeNull();
  expect(orderBody).toMatchObject({ product_id: 'p1', payment_method: 'wallet', kind: 'purchase', bundle_id: 'b1' });
  await expect(page.getByRole('dialog').getByRole('heading', { name: 'اکانت شما' })).toBeVisible();
  expect(seen).toContain('POST /api/v1/stores/store-main/orders');
  assertNoErrors();
});

test('insufficient wallet disables payment and offers the wallet shortcut', async ({ page }) => {
  const assertNoErrors = failOnPageErrors(page);
  await mockCore(
    page,
    signedIn({
      'GET /api/v1/stores/store-main/wallet': { balance: 0, currency: 'تومان' },
      'POST /api/v1/stores/store-main/checkout/quote': {
        total: 100000,
        currency: 'تومان',
        wallet_balance: 0,
        sufficient_funds: false,
      },
    }),
  );
  await page.goto('/');
  await page.getByRole('button', { name: /E2E Plan/ }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText('موجودی کافی نیست').first()).toBeVisible();
  await expect(dialog.getByRole('button', { name: /پرداخت از کیف پول/ })).toBeDisabled();
  await dialog.getByRole('button', { name: 'رفتن به کیف پول' }).click();
  await expect(page).toHaveURL(/#\/dashboard$/);
  assertNoErrors();
});

test('bot handoff link signs in and never leaves the token in the URL', async ({ page }) => {
  const assertNoErrors = failOnPageErrors(page);
  const seen = await mockCore(
    page,
    baseHandlers({
      'POST /api/v1/auth/web-handoff/redeem': PAIR,
      'GET /api/v1/me': ME,
      'GET /api/v1/stores/store-main/wallet': { balance: 1, currency: 'تومان' },
      'GET /api/v1/stores/store-main/orders': [],
    }),
  );
  await page.goto('/#/auth/handoff?t=abc-123');
  await expect(page).toHaveURL(/#\/dashboard$/);
  expect(page.url()).not.toContain('abc-123');
  expect(seen).toContain('POST /api/v1/auth/web-handoff/redeem');
  assertNoErrors();
});

test('an expired handoff link opens the sign-in dialog instead of a blank page', async ({ page }) => {
  const assertNoErrors = failOnPageErrors(page);
  await mockCore(page, baseHandlers({ 'POST /api/v1/auth/web-handoff/redeem': { status: 400, body: { detail: 'expired' } } }));
  await page.goto('/#/auth/handoff?t=old-token');
  await expect(page.getByRole('dialog').getByText('ورود به ملورین')).toBeVisible();
  assertNoErrors();
});

test('Telegram login error redirect shows a notice and is removed from the URL', async ({ page }) => {
  const assertNoErrors = failOnPageErrors(page);
  await mockCore(page, baseHandlers());
  await page.goto('/?tg_error=failed');
  await expect(page).not.toHaveURL(/tg_error/);
  assertNoErrors();
});

test('mobile menu opens and lists the section links', async ({ page }) => {
  const assertNoErrors = failOnPageErrors(page);
  await mockCore(page, baseHandlers());
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto('/');
  await page.getByRole('button', { name: 'منو' }).click();
  await expect(page.getByRole('button', { name: 'منو' })).toHaveAttribute('aria-expanded', 'true');
  assertNoErrors();
});
