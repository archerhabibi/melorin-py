import type { RequestBody, ResponseBody } from '@melorin/api-client';

/** One coupon row exactly as `GET /api/v1/admin/coupons` declares it (generated from Core's `CouponOut`). */
export type CouponRow = ResponseBody<'/api/v1/admin/coupons', 'get'>[number];
export type CouponStatus = CouponRow['status'];
/** Body of `POST /api/v1/admin/coupons`; the compiler checks every key and value below against Core's schema. */
export type CouponBody = RequestBody<'/api/v1/admin/coupons', 'post'>;

/** What the generic `Form` hands over: every field as the raw string the admin typed. */
export type CouponFormValues = Partial<Record<(typeof COUPON_FIELDS)[number][0], string>>;

/** [key, label, input type] - the order is the order on screen. */
export const COUPON_FIELDS = [
  ['code', 'کد'],
  ['pct', 'درصد تخفیف', 'number'],
  ['fixed', 'تخفیف ثابت', 'number'],
  ['max_discount', 'سقف مبلغ تخفیف', 'number'],
  ['min_amount', 'حداقل مبلغ سفارش', 'number'],
  ['max', 'سقف استفاده', 'number'],
  ['per_customer', 'سقف استفاده برای هر مشتری (پیش‌فرض ۱)', 'number'],
  ['ends', 'تاریخ پایان', 'date'],
] as const;

// Mirrors Core's `CouponIn` / `domain.coupon.validate_definition`, so a typo is caught before the round trip.
// Core stays the authority: whatever slips through comes back as its own (Persian) message and is shown as-is.
const CODE = /^[A-Za-z0-9_-]{3,50}$/;

/** blank -> null, otherwise the number (NaN when it is not one). */
const read = (raw: string | undefined): number | null => {
  const t = (raw ?? '').trim();
  return t === '' ? null : Number(t);
};
const isCount = (n: number) => Number.isInteger(n) && n > 0;
const isAmount = (n: number) => Number.isInteger(n) && n >= 0;

export type CouponBuilt = { body: CouponBody } | { error: string };

/** Validate the form and turn it into the typed create body for ONE store (`scope: 'store'`). */
export function buildCouponBody(v: CouponFormValues, storeId: string, now: number = Date.now()): CouponBuilt {
  const code = (v.code ?? '').trim();
  if (!CODE.test(code)) return { error: 'کد باید ۳ تا ۵۰ نویسه باشد و فقط حروف انگلیسی، عدد، «-» و «_» داشته باشد.' };

  const pct = read(v.pct) ?? 0;
  if (!Number.isFinite(pct) || pct < 0 || pct > 100) return { error: 'درصد تخفیف باید بین ۰ تا ۱۰۰ باشد.' };
  const fixed = read(v.fixed) ?? 0;
  if (!isAmount(fixed)) return { error: 'تخفیف ثابت باید عدد صحیح و نامنفی باشد.' };
  const percent_bp = Math.round(pct * 100);
  if (percent_bp === 0 && fixed === 0) return { error: 'تخفیف باید درصدی یا مبلغ ثابت داشته باشد.' };

  const min_amount = read(v.min_amount) ?? 0;
  if (!isAmount(min_amount)) return { error: 'حداقل مبلغ سفارش باید عدد صحیح و نامنفی باشد.' };
  const max_discount = read(v.max_discount);
  if (max_discount !== null && !isCount(max_discount))
    return { error: 'سقف مبلغ تخفیف باید عددی بزرگ‌تر از صفر باشد.' };
  const max_redemptions = read(v.max);
  if (max_redemptions !== null && !isCount(max_redemptions))
    return { error: 'سقف استفاده باید عددی بزرگ‌تر از صفر باشد.' };
  const per_customer_limit = read(v.per_customer) ?? 1;
  if (!isCount(per_customer_limit)) return { error: 'سقف استفاده برای هر مشتری باید عددی بزرگ‌تر از صفر باشد.' };

  // "valid until <date>" means the whole day, in the admin's own time zone
  let ends_at: string | null = null;
  if ((v.ends ?? '').trim()) {
    const end = new Date(`${(v.ends ?? '').trim()}T23:59:59`);
    if (Number.isNaN(end.getTime())) return { error: 'تاریخ پایان نامعتبر است.' };
    if (end.getTime() <= now) return { error: 'تاریخ پایان باید در آینده باشد.' };
    ends_at = end.toISOString();
  }

  return {
    body: {
      code,
      percent_bp,
      fixed,
      min_amount,
      max_discount,
      max_redemptions,
      per_customer_limit,
      ends_at,
      scope: 'store',
      store_id: storeId,
      funded_by: 'platform',
      status: 'active',
    },
  };
}

/** The toggle button: an active coupon is switched off; anything else (disabled, archived) is switched back on. */
export const nextStatus = (s: CouponStatus): CouponStatus => (s === 'active' ? 'disabled' : 'active');
