// Wording for the loyalty club of ONE store (Core decides every number; this only formats it).
import { fa } from './ui.jsx';

// 10000 = 1.0x. "۱٫۲۵×" for 12500.
export const multiplierLabel = (bp) => `${fa(Number(bp || 10000) / 10000)}×`;

// Progress (0..100) from the current tier's threshold toward the next one; 100 when already at the top.
export function tierProgress(current, next, lifetime) {
  if (!next) return 100;
  const from = current?.min_points ?? 0;
  const span = next.min_points - from;
  if (span <= 0) return 100;
  return Math.max(0, Math.min(100, Math.round(((lifetime - from) / span) * 100)));
}

export const TX_KIND = {
  order_earn: 'امتیاز خرید',
  first_order_bonus: 'هدیهٔ اولین خرید',
  referral_bonus: 'هدیهٔ دعوت دوست',
  admin_grant: 'تنظیم توسط فروشگاه',
  admin_deduct: 'کسر توسط فروشگاه',
  reversal: 'برگشت بابت بازگشت وجه',
  redeem: 'دریافت پاداش',
};

export const BLOCKED = {
  LOYALTY_NOT_ENOUGH_POINTS: 'امتیاز کافی نیست',
  LOYALTY_REWARD_SOLD_OUT: 'موجودی تمام شده',
  LOYALTY_REWARD_LIMIT: 'سقف دریافت شما پر شده',
  LOYALTY_REWARD_INACTIVE: 'غیرفعال است',
};
