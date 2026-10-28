// Shared wording for the referral programme and discount codes of ONE store (Core decides every number; this only formats it).
import { fa } from './ui.jsx';

export const unitOf = (currency) => ({ IRT: 'تومان', IRR: 'ریال' })[currency] || currency || '';

// A plan is { model: 'fixed' | 'percent', value, max_amount }. Percent values are basis points (۱۰۰۰ = ۱۰٪).
export function describePlan(plan, currency) {
  if (!plan) return '—';
  const unit = unitOf(currency);
  const main = plan.model === 'percent' ? `${fa(plan.value / 100)}٪` : `${fa(plan.value)} ${unit}`;
  return plan.max_amount ? `${main} (حداکثر ${fa(plan.max_amount)} ${unit})` : main;
}

const digits = (v) =>
  String(v ?? '')
    .replace(/[۰-۹]/g, (d) => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d))
    .replace(/[٠-٩]/g, (d) => '٠١٢٣٤٥٦٧٨٩'.indexOf(d));

// Typed amounts may use Persian digits; returns a non-negative integer, or null when empty/invalid.
export function toInt(v) {
  const s = digits(v).replace(/[,٬\s]/g, '');
  return /^\d+$/.test(s) ? Number(s) : null;
}

// "۱۲٫۵" (percent) -> basis points 1250; null when empty/invalid.
export function percentToBp(v) {
  const s = digits(v).replace('٫', '.').replace(/\s/g, '');
  if (!/^\d+(\.\d{1,2})?$/.test(s)) return null;
  return Math.round(Number(s) * 100);
}
