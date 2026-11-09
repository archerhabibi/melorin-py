// T42: browser E2E for the two web apps. The Core API is mocked with page.route (tests/helpers.js), so the suite needs
// only the built web apps (vite preview), not Postgres/Redis; money-path assertions on the real stack stay in scripts/e2e_smoke.py.
import { defineConfig, devices } from '@playwright/test';

const STORE = 'http://127.0.0.1:4173';
const ADMIN = 'http://127.0.0.1:4174';

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: { trace: 'retain-on-failure', locale: 'fa-IR' },
  projects: [
    { name: 'store', testMatch: /store\..*\.spec\.js/, use: { ...devices['Desktop Chrome'], baseURL: STORE } },
    { name: 'admin', testMatch: /admin\..*\.spec\.js/, use: { ...devices['Desktop Chrome'], baseURL: ADMIN } },
  ],
  webServer: [
    {
      command:
        'npm --prefix ../apps/store-web run build && npm --prefix ../apps/store-web run preview -- --port 4173 --strictPort',
      url: STORE,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
    },
    {
      command:
        'npm --prefix ../apps/admin-web run build && npm --prefix ../apps/admin-web run preview -- --port 4174 --strictPort',
      url: ADMIN,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
    },
  ],
});
