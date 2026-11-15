import { describe, expect, it } from 'vitest';
import { groups, flat } from '../src/adminNav.ts';
import { extraRoutes } from '../src/AdminExtra.tsx';
import { SECTION_AREA, sectionAllowed } from '../src/adminAccess.ts';

const where = (label) => groups.find(([, items]) => items.some((i) => i[0] === label))?.[0];

describe('admin menu structure (architecture audit §5-§6)', () => {
  it('groups infrastructure as panels, monitoring, and one operations hub that holds the bulk runs as a tab', () => {
    for (const label of ['پنل‌ها و سرورها', 'پایش و سلامت', 'عملیات مدیریتی']) {
      expect(where(label), label).toBe('زیرساخت و عملیات پنل');
      expect(SECTION_AREA[label], label).toBe('infrastructure');
    }
    expect(flat.map((x) => x[0])).not.toContain('عملیات گروهی روی پنل');
    expect(Object.keys(extraRoutes)).not.toContain('عملیات گروهی روی پنل');
  });
  it('has no stand-alone manual-tasks entry: it is a tab of reseller applications', () => {
    expect(flat.map((x) => x[0])).not.toContain('کارهای دستی');
    expect(Object.keys(extraRoutes)).not.toContain('کارهای دستی');
    expect(SECTION_AREA['کارهای دستی']).toBeUndefined();
    expect(where('درخواست‌های نمایندگی')).toBe('فروشگاه‌ها و نمایندگان');
  });
  it('keeps Telegram buttons with the owner-only system settings, matching their permission', () => {
    expect(where('دکمه‌های تلگرام')).toBe('سیستم و امنیت');
    expect(SECTION_AREA['دکمه‌های تلگرام']).toBe('system');
    expect(sectionAllowed(['communications:rw'], 'دکمه‌های تلگرام')).toBe(false);
  });
  it('gives every menu entry a route, a unique slug and an explicit permission area', () => {
    const slugs = flat.map((x) => x[2]);
    expect(new Set(slugs).size).toBe(slugs.length);
    for (const [label] of flat) {
      if (label === 'داشبورد') continue; // rendered by the shell, not a lazy route
      expect(Object.keys(extraRoutes), label).toContain(label);
    }
    for (const [label] of flat) expect(SECTION_AREA[label], label).toBeTruthy();
  });
  it('puts tickets in the notifications, communications and support group (UI grouping only), not under sales', () => {
    const group = 'اعلان‌ها، ارتباطات و پشتیبانی';
    for (const label of ['پیام همگانی', 'مرکز رویداد', 'تیکت‌ها']) expect(where(label), label).toBe(group);
    expect(where('سفارش‌ها')).toBe('فروش و عملیات');
    expect(where('تیکت‌ها')).not.toBe('فروش و عملیات');
    expect(groups.map(([name]) => name)).toHaveLength(8);
  });
});
