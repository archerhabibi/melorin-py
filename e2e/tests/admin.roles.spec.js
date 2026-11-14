// r5: sign-in methods live in Settings (owner-only), identity is a customers screen, Store Hub is the only store entry.
// Permissions below mirror apps/api/melorin/domain/admin_access.py (ROLE_PERMISSIONS).
import { expect, test } from '@playwright/test';
import { mockCore } from './helpers.js';

const ROLE_PERMS = {
  owner: 'admins audit catalog customers infrastructure orders overview payments reports resellers self support system'
    .split(' ')
    .map((a) => `${a}:rw`),
  manager: [
    'audit:r',
    'catalog:rw',
    'customers:rw',
    'infrastructure:rw',
    'orders:rw',
    'overview:rw',
    'payments:rw',
    'reports:rw',
    'resellers:rw',
    'self:rw',
    'support:rw',
  ],
  finance: [
    'catalog:r',
    'customers:r',
    'orders:rw',
    'overview:r',
    'payments:rw',
    'reports:r',
    'resellers:r',
    'self:rw',
  ],
  support: ['catalog:r', 'customers:rw', 'orders:r', 'overview:r', 'payments:r', 'self:rw', 'support:rw'],
  viewer: [
    'catalog:r',
    'customers:r',
    'infrastructure:r',
    'orders:r',
    'overview:r',
    'payments:r',
    'reports:r',
    'resellers:r',
    'self:rw',
    'support:r',
  ],
};

async function openAs(role, page, hash = '/') {
  const seen = await mockCore(page, {
    'POST /api/v1/auth/refresh': { status: 200, body: { access_token: 'test-token' } },
    'GET /api/v1/admin/me': {
      status: 200,
      body: { permissions: ROLE_PERMS[role], role, email: `${role}@example.com` },
    },
    // at least one dashboard feed must answer, otherwise the shell stays in its error state and perms never load
    'GET /api/v1/admin/dashboard': { status: 200, body: { attention: null } },
    'GET /api/v1/admin/orders': [],
    'GET /api/v1/admin/users': [],
    'GET /api/v1/admin/tickets': [],
    'GET /api/v1/admin/stores': [{ id: 's0', name: 'Main', slug: 'main', kind: 'main', status: 'active' }],
    'GET /api/v1/admin/identity-link-reviews': [],
    'GET /api/v1/admin/integrations/google': { status: 200, body: { enabled: false, client_id: '' } },
    'GET /api/v1/admin/integrations/telegram': { status: 200, body: { enabled: false } },
    'GET /api/v1/admin/integrations': {
      status: 200,
      body: {
        google: { enabled: false, client_id: '', source: 'none', suggested_origins: [] },
        telegram: {
          enabled: false,
          client_id: '',
          client_secret_set: false,
          source: 'none',
          origins: [],
          redirect_uris: [],
          ttl_seconds: 300,
          ttl_min: 60,
          ttl_max: 600,
          main_bot_username: '',
          suggested_client_id: '',
        },
        email: {},
        backup: { s3: {}, local: {} },
        admin_access: { ips: [] },
      },
    },
    'GET /api/v1/admin/settings': { status: 200, body: {} },
    'GET /api/v1/admin/feature-flags': [],
  });
  await page.goto(`/#${hash}`);
  await expect(page.getByRole('navigation', { name: 'منوی اصلی' })).toBeVisible({ timeout: 15000 });
  return seen;
}
const nav = (page) => page.getByRole('navigation', { name: 'منوی اصلی' });

for (const role of ['owner', 'manager', 'finance', 'support', 'viewer']) {
  test(`${role}: menu shows Settings and Team only for the owner; identity sits with customers`, async ({ page }) => {
    await openAs(role, page);
    const owner = role === 'owner';
    await expect(nav(page).getByRole('button', { name: 'تنظیمات' })).toHaveCount(owner ? 1 : 0);
    await expect(nav(page).getByRole('button', { name: 'تیم مدیریت' })).toHaveCount(owner ? 1 : 0);
    // identity: customers area, readable by everyone except none of the five roles lacks customers:r
    await expect(nav(page).getByRole('button', { name: 'هویت' })).toHaveCount(1);
    // the old stand-alone entries never show up in the menu
    for (const gone of ['نمایندگان', 'اپراتور پنل فروشگاه', 'حجم فروشگاه‌ها'])
      await expect(nav(page).getByRole('button', { name: gone, exact: true })).toHaveCount(0);
  });
}

test('support: the identity hub has three tabs and no sign-in tab', async ({ page }) => {
  await openAs('support', page, '/identity');
  const group = page.getByRole('radiogroup', { name: 'بخش هویت' });
  await expect(group.getByRole('radio')).toHaveCount(3);
  await expect(group.getByRole('radio', { name: 'روش‌های ورود' })).toHaveCount(0);
});

test('support: opening Settings by URL never reaches the sign-in settings API', async ({ page }) => {
  const seen = await openAs('support', page, '/settings?tab=login');
  await page.waitForTimeout(800);
  await expect(page.getByText('ورود با گوگل')).toHaveCount(0);
  expect(seen.filter((k) => k.includes('/admin/integrations'))).toEqual([]);
});

test('owner: sign-in methods are a Settings tab with Google and Telegram forms', async ({ page }) => {
  const seen = await openAs('owner', page, '/settings?tab=login');
  const group = page.getByRole('radiogroup', { name: 'بخش تنظیمات' });
  await expect(group.getByRole('radio', { name: 'روش‌های ورود' })).toHaveAttribute('aria-checked', 'true');
  await expect.poll(() => seen.includes('GET /api/v1/admin/integrations')).toBe(true);
  await expect(page.getByRole('heading', { name: /گوگل/ }).first()).toBeVisible();
});

test('owner: the tab is deep-linkable and switching tabs updates the URL', async ({ page }) => {
  await openAs('owner', page, '/settings');
  const group = page.getByRole('radiogroup', { name: 'بخش تنظیمات' });
  await group.getByRole('radio', { name: 'روش‌های ورود' }).click();
  await expect(page).toHaveURL(/#\/settings\?tab=login/);
  await group.getByRole('radio', { name: 'پشتیبان‌گیری و ایمیل' }).click();
  await expect(page).toHaveURL(/#\/settings$/);
});

test('old bookmarks land on their new homes', async ({ page }) => {
  await openAs('owner', page, '/');
  const cases = [
    ['/identity?tab=login', /#\/settings\?tab=login/],
    ['/identity-auto', /#\/identity\?tab=devices/],
    ['/resellers', /#\/stores\?tab=resellers/],
    ['/panel-admins', /#\/stores\?tab=panels/],
    ['/store-governance', /#\/stores\?tab=volume/],
  ];
  for (const [from, to] of cases) {
    await page.goto('about:blank');
    await page.goto(`/#${from}`);
    await expect(page).toHaveURL(to, { timeout: 15000 });
  }
});

test('store hub is the only entry for the absorbed tabs (owner, panels and volume tabs render)', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (e) => !/^(Error: )?\d{3}$|: \d{3}$/.test(e.message) && errors.push(e.message));
  await openAs('owner', page, '/stores?tab=panels');
  await expect(page.getByRole('radio', { name: 'دسترسی پنل' })).toHaveAttribute('aria-checked', 'true');
  await page.goto('/#/stores?tab=volume');
  await expect(page.locator('main')).not.toBeEmpty();
  expect(errors, errors.join('\n')).toEqual([]);
});
