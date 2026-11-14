// Shared wording for the referral programme and discount codes of ONE store (Core decides every number; this only formats it).
import { fa } from './ui.tsx';

export { percentToBp, toInt, unitOf } from '@melorin/web-kit/referralPlan.js';
import { unitOf } from '@melorin/web-kit/referralPlan.js';

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
