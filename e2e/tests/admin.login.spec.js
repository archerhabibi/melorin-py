import { expect, test } from '@playwright/test';
import { failOnPageErrors, mockCore } from './helpers.js';

test('admin login screen renders without page errors', async ({ page }) => {
  const assertNoErrors = failOnPageErrors(page);
  await mockCore(page, { 'POST /api/v1/auth/refresh': { status: 401, body: { detail: 'no session' } } });
  await page.goto('/');
  await expect(page.getByPlaceholder('admin@example.com')).toBeVisible();
  await expect(page.getByRole('heading', { name: /اتاق کنترل/ })).toBeVisible();
  assertNoErrors();
});

test.fixme('admin approves a card-to-card payment (needs seeded staging stack)', async () => {});
