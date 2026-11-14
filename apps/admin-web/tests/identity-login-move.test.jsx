import { afterEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { render, screen } from '@testing-library/react';
import IdentityHubView from '../src/IdentityHubView.tsx';
import { extraRoutes } from '../src/AdminExtra.tsx';
import { SECTION_AREA, sectionAllowed } from '../src/adminAccess.ts';
import { legacyHash } from '../src/infra.tsx';

const ROLES = {
  owner: ['overview:rw', 'customers:rw', 'system:rw', 'infrastructure:rw', 'resellers:rw'],
  manager: ['overview:rw', 'customers:rw', 'infrastructure:rw', 'resellers:rw'],
  finance: ['overview:r', 'payments:rw', 'orders:r'],
  support: ['overview:r', 'customers:rw', 'support:rw'],
  viewer: ['overview:r', 'customers:r'],
};

afterEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState(null, '', '/');
});

describe('sign-in methods moved from Identity to Settings', () => {
  it('identity hub has no login tab any more', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response('[]'));
    render(<IdentityHubView api={{ base: 'http://core.test' }} toast={vi.fn()} />);
    expect(await screen.findByRole('radio', { name: /نیاز به بررسی/ })).toBeInTheDocument();
    expect(screen.queryByRole('radio', { name: /روش‌های ورود/ })).toBeNull();
  });

  it('rewrites the old #/identity?tab=login bookmark to Settings', () => {
    expect(legacyHash('#/identity?tab=login')).toBe('#/settings?tab=login');
    expect(legacyHash('#/identity?tab=auto')).toBeNull();
  });

  it('Settings (owner-only area) is where sign-in methods live', () => {
    expect(SECTION_AREA['تنظیمات']).toBe('system');
    for (const role of ['manager', 'finance', 'support', 'viewer'])
      expect(sectionAllowed(ROLES[role], 'تنظیمات')).toBe(false);
    expect(sectionAllowed(ROLES.owner, 'تنظیمات')).toBe(true);
  });

  it('identity stays a customer screen for support, hidden from finance', () => {
    expect(sectionAllowed(ROLES.support, 'هویت')).toBe(true);
    expect(sectionAllowed(ROLES.finance, 'هویت')).toBe(false);
  });
});

describe('store hub is the single entry point', () => {
  it('has no stand-alone routes for the tabs it absorbed', () => {
    for (const k of ['نمایندگان', 'اپراتور پنل فروشگاه', 'حجم فروشگاه‌ها'])
      expect(Object.keys(extraRoutes)).not.toContain(k);
    expect(Object.keys(extraRoutes)).toContain('فروشگاه‌ها');
  });

  it('identity sits in the customers group, not in system', () => {
    const src = readFileSync('src/adminNav.ts', 'utf8');
    const grp = (name) => src.split(`'${name}',`)[1].split('\n  ],\n')[0];
    expect(grp('مشتریان و فروشگاه‌ها')).toContain("'identity'");
    expect(grp('سیستم')).not.toContain("'identity'");
  });
});
