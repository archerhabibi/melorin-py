import { describe, expect, it } from 'vitest';
import { buildCouponBody, nextStatus } from '../src/features/coupons/couponForm.ts';

const NOW = new Date('2026-11-21T12:00:00').getTime();
const build = (v, store = 'store-1') => buildCouponBody(v, store, NOW);

describe('buildCouponBody', () => {
  it('builds the full typed body for one store', () => {
    expect(build({ code: 'WELCOME', pct: '10', fixed: '5000', max: '25' })).toEqual({
      body: {
        code: 'WELCOME',
        percent_bp: 1000,
        fixed: 5000,
        min_amount: 0,
        max_discount: null,
        max_redemptions: 25,
        per_customer_limit: 1,
        ends_at: null,
        scope: 'store',
        store_id: 'store-1',
        funded_by: 'platform',
        status: 'active',
      },
    });
  });

  it('turns percent into basis points without float drift', () => {
    expect(build({ code: 'ABC', pct: '1.15' }).body.percent_bp).toBe(115);
    expect(build({ code: 'ABC', pct: '33.33' }).body.percent_bp).toBe(3333);
    expect(build({ code: 'ABC', pct: '100' }).body.percent_bp).toBe(10000);
  });

  it.each([
    [{ code: 'ab', pct: '10' }, 'نویسه'],
    [{ code: 'has space', pct: '10' }, 'نویسه'],
    [{ code: 'کد-فارسی', pct: '10' }, 'نویسه'],
    [{ code: 'A'.repeat(51), pct: '10' }, 'نویسه'],
    [{ code: 'ABC', pct: '100.01' }, 'بین ۰ تا ۱۰۰'],
    [{ code: 'ABC', pct: '-1' }, 'بین ۰ تا ۱۰۰'],
    [{ code: 'ABC', pct: 'abc' }, 'بین ۰ تا ۱۰۰'],
    [{ code: 'ABC' }, 'درصدی یا مبلغ ثابت'],
    [{ code: 'ABC', pct: '0', fixed: '0' }, 'درصدی یا مبلغ ثابت'],
    [{ code: 'ABC', fixed: '10.5' }, 'عدد صحیح'],
    [{ code: 'ABC', fixed: '-5' }, 'عدد صحیح'],
    [{ code: 'ABC', pct: '5', min_amount: '-1' }, 'حداقل مبلغ'],
    [{ code: 'ABC', pct: '5', max_discount: '0' }, 'سقف مبلغ تخفیف'],
    [{ code: 'ABC', pct: '5', max: '0' }, 'سقف استفاده باید'],
    [{ code: 'ABC', pct: '5', per_customer: '0' }, 'هر مشتری'],
    [{ code: 'ABC', pct: '5', ends: '2026-11-20' }, 'در آینده'],
    [{ code: 'ABC', pct: '5', ends: '2020-01-01' }, 'در آینده'],
    [{ code: 'ABC', pct: '5', ends: 'not-a-date' }, 'نامعتبر'],
  ])('rejects %j', (values, hint) => {
    const out = build(values);
    expect(out.body).toBeUndefined();
    expect(out.error).toContain(hint);
  });

  it('lets a coupon run until the end of today', () => {
    expect(build({ code: 'ABC', pct: '5', ends: '2026-11-21' }).body.ends_at).toBe(
      new Date('2026-11-21T23:59:59').toISOString(),
    );
  });

  it('accepts the code characters Core accepts and trims the rest', () => {
    expect(build({ code: '  Ramadan_1405-VIP  ', pct: '10' }).body.code).toBe('Ramadan_1405-VIP');
  });

  it('treats a blank optional field as "not set" and a date as the end of that local day', () => {
    const { body } = build({ code: 'ABC', pct: '5', max_discount: ' ', max: '', per_customer: '', ends: '2026-11-22' });
    expect(body).toMatchObject({ max_discount: null, max_redemptions: null, per_customer_limit: 1 });
    expect(body.ends_at).toBe(new Date('2026-11-22T23:59:59').toISOString());
  });
});

describe('nextStatus', () => {
  it('switches an active coupon off and anything else back on', () => {
    expect(nextStatus('active')).toBe('disabled');
    expect(nextStatus('disabled')).toBe('active');
    expect(nextStatus('archived')).toBe('active');
  });
});
