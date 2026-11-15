import { describe, expect, it } from 'vitest';
import { groups } from '../src/app/adminNav.ts';
import { canWrite, sectionAllowed } from '../src/app/adminAccess.ts';

// Mirrors apps/api/melorin/domain/admin_access.py GRANTS (the server stays the authority; this pins what the menu shows per role).
const ALL = ['overview', 'reports', 'orders', 'payments', 'catalog', 'infrastructure', 'resellers', 'customers', 'support'];
const perms = (map) => Object.entries(map).map(([area, mode]) => `${area}:${mode}`);
const ROLES = {
  owner: perms({ ...Object.fromEntries([...ALL, 'system', 'audit', 'admins', 'self'].map((a) => [a, 'rw'])) }),
  manager: perms({ ...Object.fromEntries(ALL.map((a) => [a, 'rw'])), audit: 'r', self: 'rw' }),
  finance: perms({ overview: 'r', reports: 'r', orders: 'rw', payments: 'rw', catalog: 'r', resellers: 'r', customers: 'r', self: 'rw' }),
  support: perms({ overview: 'r', orders: 'r', payments: 'r', catalog: 'r', customers: 'rw', support: 'rw', self: 'rw' }),
  viewer: perms({ ...Object.fromEntries(ALL.map((a) => [a, 'r'])), self: 'rw' }),
};
const COMMS = 'اعلان‌ها، ارتباطات و پشتیبانی';
const visible = (role) => groups.map(([name, items]) => [name, items.filter(([label]) => sectionAllowed(ROLES[role], label)).map((i) => i[0])]);
const commsOf = (role) => visible(role).find(([n]) => n === COMMS)[1];

describe('admin menu per role (tickets live in the notifications / communications / support group)', () => {
  it('owner and manager see the whole communications group', () => {
    for (const role of ['owner', 'manager']) expect(commsOf(role)).toEqual(['پیام همگانی', 'مرکز رویداد', 'تیکت‌ها']);
  });
  it('support works tickets with write access; finance does not see them at all', () => {
    expect(commsOf('support')).toContain('تیکت‌ها');
    expect(canWrite(ROLES.support, 'تیکت‌ها')).toBe(true);
    expect(commsOf('finance')).not.toContain('تیکت‌ها');
  });
  it('viewer sees tickets read-only', () => {
    expect(commsOf('viewer')).toContain('تیکت‌ها');
    expect(canWrite(ROLES.viewer, 'تیکت‌ها')).toBe(false);
  });
  it('only the owner reaches the system group settings and Telegram buttons', () => {
    const sys = (role) => visible(role).find(([n]) => n === 'سیستم و امنیت')[1];
    expect(sys('owner')).toEqual(expect.arrayContaining(['تنظیمات', 'دکمه‌های تلگرام', 'تیم مدیریت']));
    for (const role of ['manager', 'finance', 'support', 'viewer']) {
      expect(sys(role)).not.toContain('تنظیمات');
      expect(sys(role)).not.toContain('دکمه‌های تلگرام');
      expect(sys(role)).not.toContain('تیم مدیریت');
    }
  });
  it('support never sees infrastructure screens', () => {
    const infra = visible('support').find(([n]) => n === 'زیرساخت و عملیات پنل')[1];
    expect(infra).toEqual([]);
  });
});
