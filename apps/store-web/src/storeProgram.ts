// Shared wording for the referral programme and discount codes of ONE store (Core decides every number; this only formats it).
import { fa } from './ui.tsx';

const UNITS: Record<string, string> = { IRT: 'تومان', IRR: 'ریال' };
export const unitOf = (currency?: string | null): string => (currency ? UNITS[currency] || currency : '');

// A plan is { model: 'fixed' | 'percent', value, max_amount }. Percent values are basis points (۱۰۰۰ = ۱۰٪).
export interface Plan {
  model: 'fixed' | 'percent';
  value: number;
  max_amount?: number | null;
}

export function describePlan(plan: Plan | null | undefined, currency?: string | null): string {
  if (!plan) return '—';
  const unit = unitOf(currency);
  const main = plan.model === 'percent' ? `${fa(plan.value / 100)}٪` : `${fa(plan.value)} ${unit}`;
  return plan.max_amount ? `${main} (حداکثر ${fa(plan.max_amount)} ${unit})` : main;
}

const digits = (v: unknown): string =>
  String(v ?? '')
    .replace(/[۰-۹]/g, (d) => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(d)))
    .replace(/[٠-٩]/g, (d) => String('٠١٢٣٤٥٦٧٨٩'.indexOf(d)));

// Typed amounts may use Persian digits; returns a non-negative integer, or null when empty/invalid.
export function toInt(v: unknown): number | null {
  const s = digits(v).replace(/[,٬\s]/g, '');
  return /^\d+$/.test(s) ? Number(s) : null;
}

// "۱۲٫۵" (percent) -> basis points 1250; null when empty/invalid.
export function percentToBp(v: unknown): number | null {
  const s = digits(v).replace('٫', '.').replace(/\s/g, '');
  if (!/^\d+(\.\d{1,2})?$/.test(s)) return null;
  return Math.round(Number(s) * 100);
}
