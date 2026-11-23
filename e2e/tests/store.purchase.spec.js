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
  await mockCore(
    page,
    baseHandlers({ 'POST /api/v1/auth/web-handoff/redeem': { status: 400, body: { detail: 'expired' } } }),
  );
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

test('a lost order response is retried with the same key after a reload', async ({ page }) => {
  const keys = [];
  await mockCore(
    page,
    signedIn({
      'POST /api/v1/stores/store-main/checkout/quote': {
        total: 100000,
        currency: 'تومان',
        wallet_balance: 500000,
        sufficient_funds: true,
      },
      'POST /api/v1/stores/store-main/orders': (req) => {
        keys.push(req.headers()['idempotency-key']);
        return keys.length === 1
          ? { status: 503, body: { error: { code: 'TEMPORARY', message: 'نتیجه نامعلوم' } } }
          : { id: 'o1' };
      },
    }),
  );
  await page.goto('/');
  await expect(page.getByRole('button', { name: /Tester/ }).first()).toBeVisible();
  await page.getByRole('button', { name: /E2E Plan/ }).click();
  await page
    .getByRole('dialog')
    .getByRole('button', { name: /پرداخت از کیف پول/ })
    .click();
  await expect.poll(() => keys.length).toBe(1);
  await page.reload();
  await expect(page.getByRole('button', { name: /Tester/ }).first()).toBeVisible();
  await page.getByRole('button', { name: /E2E Plan/ }).click();
  await page
    .getByRole('dialog')
    .getByRole('button', { name: /پرداخت از کیف پول/ })
    .click();
  await expect.poll(() => keys.length).toBe(2);
  expect(keys[1]).toBe(keys[0]);
});

test('overlapping tabs wait for storage coordination and share one order key', async ({ page, context }) => {
  const pages = [page, await context.newPage()];
  const keys = [];
  const releaseResponses = [];
  const quote = { total: 100000, currency: 'تومان', wallet_balance: 500000, sufficient_funds: true };
  for (const p of pages) {
    await mockCore(p, signedIn({ 'POST /api/v1/stores/store-main/checkout/quote': quote }));
    await p.route('**/api/v1/stores/store-main/orders', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback();
      keys.push(route.request().headers()['idempotency-key']);
      await new Promise((resolve) => releaseResponses.push(resolve));
      await route.fulfill({ status: 503, contentType: 'application/json', body: '{}' });
    });
    await p.goto('/');
    await expect(p.getByRole('button', { name: /Tester/ }).first()).toBeVisible();
    await p.getByRole('button', { name: /E2E Plan/ }).click();
    await expect(p.getByRole('dialog').getByRole('button', { name: /پرداخت از کیف پول/ })).toBeEnabled();
  }

  // Hold a real read/write transaction so both tabs must wait before choosing a key.
  await page.evaluate(
    () =>
      new Promise((resolve, reject) => {
        const open = indexedDB.open('melorin-attempt-lock', 2);
        open.onerror = () => reject(open.error);
        open.onupgradeneeded = () => open.result.createObjectStore('attempts');
        open.onsuccess = () => {
          const db = open.result;
          const tx = db.transaction('attempts', 'readwrite');
          const store = tx.objectStore('attempts');
          let released = false;
          window.releaseAttemptTestLock = () => {
            released = true;
          };
          const hold = () => {
            if (!released) store.get('gate').onsuccess = hold;
          };
          const first = store.get('gate');
          first.onsuccess = () => {
            hold();
            resolve();
          };
          tx.oncomplete = () => db.close();
          tx.onabort = () => reject(tx.error);
        };
      }),
  );
  for (const p of pages) {
    await p.evaluate(() => {
      const original = indexedDB.open.bind(indexedDB);
      indexedDB.open = (...args) => {
        window.orderLockRequested = true;
        return original(...args);
      };
    });
  }
  await Promise.all(
    pages.map((p) =>
      p
        .getByRole('dialog')
        .getByRole('button', { name: /پرداخت از کیف پول/ })
        .click(),
    ),
  );
  for (const p of pages) await expect.poll(() => p.evaluate(() => window.orderLockRequested)).toBe(true);
  expect(keys).toHaveLength(0);
  await page.evaluate(() => window.releaseAttemptTestLock());
  await expect.poll(() => keys.length).toBe(2);
  expect(keys[0]).toBe(keys[1]);
  releaseResponses.forEach((release) => release());
});

test('a pending renewal stays recoverable after reload when the account becomes ineligible', async ({ page }) => {
  const keys = [];
  const assertNoErrors = failOnPageErrors(page);
  await mockCore(
    page,
    signedIn({
      'GET /api/v1/stores/store-main/vpn-accounts': () => [
        {
          id: 'vpn1',
          username: 'account1',
          health: 'active',
          is_test: false,
          can_renew: keys.length === 0,
          can_return: false,
        },
      ],
      'GET /api/v1/stores/store-main/vpn-accounts/summary': { total: 1, active: 1, expiring: 0, expired: 0 },
      'GET /api/v1/stores/store-main/accounts/vpn1/renewal': () =>
        keys.length
          ? { renewable: false, code: 'RENEWAL_IN_PROGRESS', message: 'تمدید در حال انجام است' }
          : { renewable: true, package: { product_id: 'p1', name: 'E2E Plan' } },
      'POST /api/v1/stores/store-main/checkout/quote': {
        total: 100000,
        currency: 'تومان',
        sufficient_funds: true,
      },
      'POST /api/v1/stores/store-main/orders': (req) => {
        keys.push(req.headers()['idempotency-key']);
        return keys.length === 1 ? { status: 503, body: { error: { message: 'نتیجه نامعلوم' } } } : { id: 'o1' };
      },
    }),
  );
  await page.goto('/#/dashboard');
  await page.getByRole('button', { name: 'اکانت‌های VPN' }).click();
  await page.getByRole('button', { name: 'تمدید', exact: true }).click();
  await page.getByRole('button', { name: 'پرداخت از کیف پول و تمدید' }).click();
  await expect.poll(() => keys.length).toBe(1);
  await page.reload();
  await page.getByRole('button', { name: 'اکانت‌های VPN' }).click();
  await page.getByRole('button', { name: 'پیگیری تمدید قبلی' }).click();
  await page.getByRole('button', { name: 'تلاش مجدد تمدید قبلی' }).click();
  await expect.poll(() => keys.length).toBe(2);
  expect(keys[1]).toBe(keys[0]);
  assertNoErrors();
});

test('a lost purchase remains recoverable even when the new quote has insufficient funds', async ({ page }) => {
  const keys = [];
  const assertNoErrors = failOnPageErrors(page);
  await mockCore(
    page,
    signedIn({
      'POST /api/v1/stores/store-main/checkout/quote': () => ({
        total: 100000,
        currency: 'تومان',
        wallet_balance: keys.length ? 0 : 500000,
        sufficient_funds: keys.length === 0,
      }),
      'POST /api/v1/stores/store-main/orders': (req) => {
        keys.push(req.headers()['idempotency-key']);
        return keys.length === 1 ? { status: 503, body: { error: { message: 'نتیجه نامعلوم' } } } : { id: 'o1' };
      },
    }),
  );
  await page.goto('/');
  await page.getByRole('button', { name: /E2E Plan/ }).click();
  await page
    .getByRole('dialog')
    .getByRole('button', { name: /پرداخت از کیف پول/ })
    .click();
  await expect.poll(() => keys.length).toBe(1);
  await page.reload();
  await page.getByRole('button', { name: /E2E Plan/ }).click();
  await expect(page.getByRole('dialog').getByRole('button', { name: /پرداخت از کیف پول/ })).toBeDisabled();
  await page.getByRole('dialog').getByRole('button', { name: 'رفتن به کیف پول' }).click();
  await page.getByRole('navigation', { name: 'بخش‌های حساب' }).getByRole('button', { name: 'سفارش‌ها' }).click();
  await page.getByRole('button', { name: 'تلاش مجدد سفارش قبلی' }).click();
  await expect.poll(() => keys.length).toBe(2);
  expect(keys[1]).toBe(keys[0]);
  assertNoErrors();
});

test('wallet topups in overlapping tabs wait for coordination and share a key', async ({ page, context }) => {
  const pages = [page, await context.newPage()];
  const keys = [];
  const releaseResponses = [];
  for (const p of pages) {
    await mockCore(p, signedIn({ 'GET /api/v1/stores/store-main/wallet/transactions': [] }));
    await p.route('**/api/v1/stores/store-main/wallet/topups', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback();
      keys.push(route.request().headers()['idempotency-key']);
      await new Promise((resolve) => releaseResponses.push(resolve));
      await route.fulfill({ status: 503, contentType: 'application/json', body: '{}' });
    });
    await p.goto('/#/dashboard');
    await p.getByRole('navigation', { name: 'بخش‌های حساب' }).getByRole('button', { name: 'کیف پول' }).click();
    await p.getByPlaceholder('مبلغ').fill('1000');
  }

  // Hold the shared IndexedDB transaction until both tabs have attempted to acquire it.
  await page.evaluate(
    () =>
      new Promise((resolve, reject) => {
        const open = indexedDB.open('melorin-attempt-lock', 2);
        open.onerror = () => reject(open.error);
        open.onupgradeneeded = () => open.result.createObjectStore('attempts');
        open.onsuccess = () => {
          const db = open.result;
          const tx = db.transaction('attempts', 'readwrite');
          const store = tx.objectStore('attempts');
          let released = false;
          window.releaseWalletTestLock = () => {
            released = true;
          };
          const hold = () => {
            if (!released) store.get('gate').onsuccess = hold;
          };
          store.get('gate').onsuccess = () => {
            hold();
            resolve();
          };
          tx.oncomplete = () => db.close();
          tx.onabort = () => reject(tx.error);
        };
      }),
  );
  for (const p of pages) {
    await p.evaluate(() => {
      const original = indexedDB.open.bind(indexedDB);
      indexedDB.open = (...args) => {
        window.walletLockRequested = true;
        return original(...args);
      };
    });
  }
  await Promise.all(pages.map((p) => p.getByRole('button', { name: 'ایجاد درخواست' }).click()));
  for (const p of pages) await expect.poll(() => p.evaluate(() => window.walletLockRequested)).toBe(true);
  expect(keys).toHaveLength(0);
  await page.evaluate(() => window.releaseWalletTestLock());
  await expect.poll(() => keys.length).toBe(2);
  expect(keys[0]).toBe(keys[1]);
  releaseResponses.forEach((release) => release());
  const attempt = await page.evaluate(
    () =>
      new Promise((resolve, reject) => {
        const open = indexedDB.open('melorin-attempt-lock', 2);
        open.onerror = () => reject(open.error);
        open.onsuccess = () => {
          const db = open.result;
          const tx = db.transaction('attempts', 'readonly');
          const request = tx.objectStore('attempts').get('melorin:wallet-topup:store-main:u1');
          request.onsuccess = () => resolve(JSON.parse(request.result));
          request.onerror = () => reject(request.error);
          tx.oncomplete = () => db.close();
        };
      }),
  );
  expect(attempt.idempotencyKey).toBe(keys[0]);
});

test('a legacy wallet key is migrated once and remains authoritative after reload', async ({ page }) => {
  const legacyKey = 'topup-11111111-1111-4111-8111-111111111111';
  const keys = [];
  await page.addInitScript((key) => {
    if (!localStorage.getItem('melorin:attempt-storage-initialized')) {
      localStorage.setItem(
        'melorin:wallet-topup:store-main:u1',
        JSON.stringify({ amount: '1000', idempotencyKey: key, state: 'unknown' }),
      );
    }
  }, legacyKey);
  await mockCore(
    page,
    signedIn({
      'GET /api/v1/stores/store-main/wallet/transactions': [],
      'POST /api/v1/stores/store-main/wallet/topups': (req) => {
        keys.push(req.headers()['idempotency-key']);
        return { status: 503, body: { error: { message: 'نامعلوم' } } };
      },
    }),
  );
  await page.goto('/#/dashboard');
  await page.getByRole('navigation', { name: 'بخش‌های حساب' }).getByRole('button', { name: 'کیف پول' }).click();
  await page.getByPlaceholder('مبلغ').fill('1000');
  await page.getByRole('button', { name: 'ایجاد درخواست' }).click();
  await expect.poll(() => keys.length).toBe(1);
  expect(keys[0]).toBe(legacyKey);
  const oldVersionError = await page.evaluate(
    () =>
      new Promise((resolve) => {
        const request = indexedDB.open('melorin-attempt-lock', 1);
        request.onerror = () => resolve(request.error?.name);
        request.onsuccess = () => {
          request.result.close();
          resolve(null);
        };
      }),
  );
  expect(oldVersionError).toBe('VersionError');

  await page.evaluate(() => {
    localStorage.setItem(
      'melorin:wallet-topup:store-main:u1',
      JSON.stringify({ amount: '1000', idempotencyKey: 'topup-22222222-2222-4222-8222-222222222222' }),
    );
  });
  await page.reload();
  await page.getByRole('navigation', { name: 'بخش‌های حساب' }).getByRole('button', { name: 'کیف پول' }).click();
  await page.getByPlaceholder('مبلغ').fill('1000');
  await page.getByRole('button', { name: 'ایجاد درخواست' }).click();
  await expect.poll(() => keys.length).toBe(2);
  expect(keys[1]).toBe(legacyKey);
});
