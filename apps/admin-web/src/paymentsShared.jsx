// Payments screen — review queue, KPIs, filters, detail drawer and gateway settings.
// Data comes only from GET /api/v1/admin/payments (+ /settings); actions use the existing
// /review, /refund and /receipt endpoints, so no backend change is required.

import { Coins, CreditCard, Globe, Landmark, Star, Wallet } from 'lucide-react';

import { num, tint } from './kit.jsx';
import { dt } from './ui.jsx';

export const PAGE = 15;
export const REVIEWABLE = ['pending', 'review', 'receipt_submitted', 'awaiting_review'];

export const PROVIDERS = {
  manual_card: { label: 'کارت‌به‌کارت', Icon: CreditCard },
  zarinpal: { label: 'زرین‌پال', Icon: Landmark },
  external_gateway: { label: 'درگاه خارجی', Icon: Globe },
  crypto: { label: 'ارز دیجیتال', Icon: Coins },
  telegram_stars: { label: 'ستاره تلگرام', Icon: Star },
};
export const prov = (k) => PROVIDERS[k] || { label: k || 'نامشخص', Icon: Wallet };
export const CUR = { IRT: 'تومان', IRR: 'ریال' };
export const cur = (c) => CUR[c] || c || '';

export const reviewable = (p) => REVIEWABLE.includes(p.status) && p.has_receipt;
export const refundable = (p) => p.status === 'succeeded';
export const FILTERS = {
  all: () => true,
  review: reviewable,
  succeeded: (p) => p.status === 'succeeded',
  failed: (p) => p.status === 'failed',
  closed: (p) => p.status === 'refunded' || p.status === 'cancelled',
};

export const rtf = new Intl.RelativeTimeFormat('fa', { numeric: 'auto' });
export function ago(v) {
  if (!v) return '-';
  const s = Math.round((new Date(v).getTime() - Date.now()) / 1000);
  const a = Math.abs(s);
  if (a < 60) return rtf.format(s, 'second');
  if (a < 3600) return rtf.format(Math.round(s / 60), 'minute');
  if (a < 86400) return rtf.format(Math.round(s / 3600), 'hour');
  if (a < 2592000) return rtf.format(Math.round(s / 86400), 'day');
  return dt(v);
}
export const sumBy = (rows) => {
  const m = new Map();
  rows.forEach((p) => m.set(p.currency, (m.get(p.currency) || 0) + (p.amount || 0)));
  return [...m].map(([c, a]) => `${num(a)} ${cur(c)}`).join(' · ') || '۰';
};
export const copy = (text, toast) =>
  navigator.clipboard?.writeText(String(text)).then(
    () => toast('کپی شد'),
    () => toast('کپی ناموفق بود'),
  );

// ---------------------------------------------------------------- small parts
/** KpiBar cell for a text value (money per currency); Stat only renders numbers. */
export function Metric({ Icon, tone, label, value, sub, loading }) {
  return (
    <div className="kpi">
      <span className="tile h-11 w-11" style={tint(tone)}>
        <Icon size={19} />
      </span>
      <span className="min-w-0">
        {loading ? (
          <span className="skel block h-6 w-28" />
        ) : (
          <span className="num block truncate text-lg font-extrabold leading-tight">{value}</span>
        )}
        <span className="mt-1 block truncate text-xs text-[var(--mu)]">{label}</span>
        {sub && !loading && <span className="mt-0.5 block truncate text-[11px] text-[var(--mu)]">{sub}</span>}
      </span>
    </div>
  );
}

export function ProviderChip({ k, size = 16 }) {
  const { label, Icon } = prov(k);
  return (
    <span className="inline-flex items-center gap-2">
      <span className="tile h-8 w-8 !rounded-lg bg-[var(--mb)] text-[var(--mu)]">
        <Icon size={size} />
      </span>
      <span className="font-bold">{label}</span>
    </span>
  );
}

export function Amount({ p, big = false }) {
  return (
    <span className={`num font-extrabold ${big ? 'text-2xl' : ''}`}>
      {num(p.amount)}
      <span className="mr-1.5 text-[11px] font-medium text-[var(--mu)]">{cur(p.currency)}</span>
    </span>
  );
}

