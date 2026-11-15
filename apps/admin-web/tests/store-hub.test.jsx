import { describe, expect, it } from 'vitest';
import { extraRoutes } from '../src/AdminExtra.tsx';
import { SECTION_AREA, sectionAllowed } from '../src/adminAccess.ts';

describe('store hub', () => {
  it('the stores section is routed to the hub, and every tab section keeps its permission area', () => {
    expect(Object.keys(extraRoutes)).toContain('فروشگاه‌ها');
    for (const s of ['فروشگاه‌ها', 'نمایندگان', 'اپراتور پنل فروشگاه', 'حجم فروشگاه‌ها'])
      expect(SECTION_AREA[s]).toBeTruthy();
  });

  it('a role with only the resellers area does not see the infrastructure tabs', () => {
    const perms = ['resellers:rw'];
    expect(sectionAllowed(perms, 'نمایندگان')).toBe(true);
    expect(sectionAllowed(perms, 'اپراتور پنل فروشگاه')).toBe(false);
    expect(sectionAllowed(perms, 'حجم فروشگاه‌ها')).toBe(false);
  });
});
