import { describe, expect, it } from 'vitest';
import { legacyHash } from '../src/infra.tsx';
import { extraRoutes } from '../src/AdminExtra.tsx';
import { SECTION_AREA, sectionAllowed } from '../src/adminAccess.ts';

describe('store hub', () => {
  it('old bookmarks of the merged screens land on the matching hub tab', () => {
    expect(legacyHash('#/resellers')).toBe('#/stores?tab=resellers');
    expect(legacyHash('#/panel-admins')).toBe('#/stores?tab=panels');
    expect(legacyHash('#/store-governance')).toBe('#/stores?tab=volume');
    expect(legacyHash('#/stores')).toBeNull();
  });

  it('the stores section is routed to the hub, and every tab section keeps its permission area', () => {
    expect(Object.keys(extraRoutes)).toContain('فروشگاه‌ها');
    for (const s of ['فروشگاه‌ها', 'نمایندگان', 'ادمین‌های پنل', 'حجم فروشگاه‌ها']) expect(SECTION_AREA[s]).toBeTruthy();
  });

  it('a role with only the resellers area does not see the infrastructure tabs', () => {
    const perms = ['resellers:rw'];
    expect(sectionAllowed(perms, 'نمایندگان')).toBe(true);
    expect(sectionAllowed(perms, 'ادمین‌های پنل')).toBe(false);
    expect(sectionAllowed(perms, 'حجم فروشگاه‌ها')).toBe(false);
  });
});
