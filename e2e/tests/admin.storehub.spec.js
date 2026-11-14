import { expect, test } from '@playwright/test';
import { failOnPageErrors, mockCore } from './helpers.js';

const PERMS = [
  'overview:rw',
  'resellers:rw',
  'catalog:rw',
  'infrastructure:rw',
  'payments:rw',
  'customers:rw',
  'system:rw',
  'self:rw',
];
const reseller = {
  id: 's9',
  name: 'Acme Store',
  slug: 'acme',
  status: 'active',
  api_enabled: false,
  bot: { state: 'no_token' },
  owner: null,
  customers: 0,
  currency: 'IRT',
};

async function openHub(page, tab) {
  const seen = await mockCore(page, {
    'POST /api/v1/auth/refresh': { body: { access_token: 'test-token' } },
    'GET /api/v1/admin/me': { body: { permissions: PERMS, role: 'owner' } },
    'GET /api/v1/admin/stores': [{ id: 's0', name: 'Main', slug: 'main', kind: 'main', status: 'active' }],
    'GET /api/v1/admin/resellers': [reseller],
    'GET /api/v1/admin/stores/s9/reseller-prices': [
      {
        product_id: 'p1',
        name: 'Monthly VPN',
        currency: 'IRT',
        customer_price: 90000,
        cost_floor: 70000,
        state: 'ok',
        bundles: [],
      },
    ],
    'PUT /api/v1/admin/reseller-stores/s9/api': { body: { store_id: 's9', api_enabled: true } },
  });
  await page.goto(`/#/stores${tab ? `?tab=${tab}` : ''}`);
  return seen;
}

test('store hub shows all seven tabs and deep links to a tab', async ({ page }) => {
  const assertNoErrors = failOnPageErrors(page);
  await openHub(page, 'prices');
  const group = page.getByRole('radiogroup', { name: 'بخش فروشگاه' });
  await expect(group).toBeVisible();
  await expect(group.getByRole('radio')).toHaveCount(7);
  await expect(group.getByRole('radio', { name: 'قیمت‌ها' })).toHaveAttribute('aria-checked', 'true');
  assertNoErrors();
});

test('prices tab is read-only and lists a reseller price table', async ({ page }) => {
  await openHub(page, 'prices');
  await page.getByLabel('فروشگاه نماینده').selectOption('s9');
  await expect(page.getByText('Monthly VPN')).toBeVisible();
  await expect(page.locator('main input, main textarea')).toHaveCount(0);
});

test('API tab flips the switch with a PUT', async ({ page }) => {
  const seen = await openHub(page, 'api');
  await page.getByRole('switch', { name: /Acme Store/ }).click();
  await expect.poll(() => seen.some((k) => k.startsWith('PUT /api/v1/admin/reseller-stores/s9/api'))).toBe(true);
});

test('old panel-ops notices bookmark lands on the notices tab', async ({ page }) => {
  await openHub(page, '');
  await page.goto('about:blank');
  await page.goto('/#/panel-ops?tab=notices');
  await expect(page).toHaveURL(/#\/stores\?tab=notices/);
  await expect(page.getByRole('radio', { name: 'اعلان‌ها' })).toHaveAttribute('aria-checked', 'true', {
    timeout: 15000,
  });
});

const ROUTES =
  'admin-team audit broadcasts bulk-operations bundles button-styles coupons event-center home identity infra-health loyalty-club manual-tasks my-account orders panel-ops panels payments products referral-programs reports reseller-applications settings stores tickets users vpn'.split(
    ' ',
  );

test('every admin menu route renders without a page error or a blank screen', async ({ page }) => {
  const errors = [];
  // unmocked endpoints answer 404; views that reject with just the status are mock noise, anything else is a real error
  page.on('pageerror', (e) => !/^(Error: )?\d{3}$|: \d{3}$/.test(e.message) && errors.push(e.message));
  await openHub(page, '');
  for (const slug of ROUTES) {
    await page.goto(`/#/${slug === 'home' ? '' : slug}`);
    await page.waitForTimeout(250);
    await expect(page.locator('main')).not.toBeEmpty();
  }
  expect(errors, errors.join('\n')).toEqual([]);
});
