// Pure helpers for the Reports & charts screen (no React, no DOM): formatting, labels, insights, chart geometry.
// Kept separate so every rule here is unit-tested (tests/reports-logic.test.js).
import { dayLong } from './charts.jsx';

export const nf = new Intl.NumberFormat('fa-IR');
export const cf = new Intl.NumberFormat('fa-IR', { notation: 'compact', maximumFractionDigits: 1 });
export const fmt = (n) => nf.format(Math.round(Number(n) || 0));
export const fmtCompact = (n) => cf.format(Math.round(Number(n) || 0));
export const fmtPct = (n) =>
  `${new Intl.NumberFormat('fa-IR', { maximumFractionDigits: 1 }).format(Math.abs(Number(n) || 0))}٪`;
export const fmtBytes = (n) => {
  const v = Number(n) || 0;
  if (v < 1024) return `${fmt(v)} B`;
  const u = ['KB', 'MB', 'GB', 'TB', 'PB'];
  let x = v / 1024;
  let i = 0;
  while (x >= 1024 && i < u.length - 1) {
    x /= 1024;
    i += 1;
  }
  return `${new Intl.NumberFormat('fa-IR', { maximumFractionDigits: 1 }).format(x)} ${u[i]}`;
};

export const METHOD_LABELS = {
  wallet: 'کیف پول',
  manual_card: 'کارت به کارت',
  gateway: 'درگاه پرداخت',
  free: 'رایگان',
};
export const CHANNEL_LABELS = { web: 'وب‌سایت', telegram: 'ربات تلگرام', api: 'API نمایندگان', admin: 'پنل ادمین' };
export const KIND_LABELS = { purchase: 'خرید جدید', renewal: 'تمدید', test: 'اکانت تست' };
export const PROVIDER_LABELS = { manual_card: 'کارت به کارت', zarinpal: 'زرین‌پال' };
export const STORE_KIND_LABELS = { main: 'فروشگاه اصلی', reseller: 'نماینده', unknown: 'نامشخص' };
export const pick = (map, key) => map[key] || String(key);

// The API numbers weekdays Monday=0 .. Sunday=6; the Persian week starts on Saturday.
export const WEEK_ORDER = [5, 6, 0, 1, 2, 3, 4];
export const WEEKDAY_FA = { 0: 'دوشنبه', 1: 'سه‌شنبه', 2: 'چهارشنبه', 3: 'پنجشنبه', 4: 'جمعه', 5: 'شنبه', 6: 'یکشنبه' };

/** Direction + wording of a change vs the previous period. ``invert``: a rise is bad (refunds, failures). */
export function deltaInfo(delta, { invert = false } = {}) {
  if (delta === null || delta === undefined) return { dir: 'none', good: null, text: 'بدون دوره قبل' };
  if (Math.abs(delta) < 0.05) return { dir: 'flat', good: null, text: 'بدون تغییر' };
  const up = delta > 0;
  return { dir: up ? 'up' : 'down', good: invert ? !up : up, text: `${fmtPct(delta)} ${up ? 'بیشتر' : 'کمتر'}` };
}

/** Donut segments on a 100-unit circumference: each gets a dash length and the offset where it starts (2-unit gap). */
export function donutSegments(items, gap = 1.2) {
  const total = items.reduce((a, x) => a + Math.max(0, x.value), 0);
  if (!total) return [];
  let acc = 0;
  const visible = items.filter((x) => x.value > 0);
  return visible.map((x) => {
    const pct = (x.value / total) * 100;
    // a lone segment is a full ring: no gap to leave (judge by what is drawn, not by how many rows came in)
    const seg = { ...x, pct, dash: Math.max(0.4, pct - (visible.length > 1 ? gap : 0)), offset: -acc };
    acc += pct;
    return seg;
  });
}

/** Share of ``part`` in ``whole`` as 0..100 (0 when empty). */
export const share = (part, whole) => (whole ? (part / whole) * 100 : 0);

/** Fold a long tail into one "other" row so a donut never needs more series than the palette validates for. */
export function foldTail(rows, max = 5, other = 'سایر') {
  if (rows.length <= max) return rows;
  const head = rows.slice(0, max - 1);
  const tail = rows.slice(max - 1);
  return [...head, { key: '__other', label: other, value: tail.reduce((a, x) => a + x.value, 0) }];
}

/** 0..1 intensity of a heatmap cell (sqrt scale so one huge hour does not wash out the rest). */
export const heatLevel = (count, max) => (max > 0 && count > 0 ? Math.max(0.12, Math.sqrt(count / max)) : 0);

/** Plain-language findings derived from the payload. Each has a tone (ok | wn | in | bd) and Persian text. */
export function buildInsights(d) {
  if (!d) return [];
  const out = [];
  const k = d.kpis || {};
  const cur = d.currency || '';
  const rev = k.revenue;
  if (rev && rev.delta_pct !== null && rev.delta_pct !== undefined && (rev.value || rev.previous)) {
    const up = rev.delta_pct >= 0;
    out.push({
      id: 'revenue-delta',
      tone: up ? 'ok' : 'wn',
      text: `فروش این بازه ${fmtPct(rev.delta_pct)} ${up ? 'بیشتر' : 'کمتر'} از بازه‌ی قبلی بود (${fmt(rev.value)} در برابر ${fmt(rev.previous)} ${cur}).`,
    });
  }
  const h = d.highlights || {};
  if (h.best_day && h.best_day_revenue) {
    out.push({
      id: 'best-day',
      tone: 'in',
      text: `بهترین روز فروش ${dayLong(h.best_day)} بود با ${fmt(h.best_day_revenue)} ${cur}.`,
    });
  }
  const peak = d.heatmap?.peak;
  if (peak) {
    out.push({
      id: 'peak-hour',
      tone: 'in',
      text: `پرفروش‌ترین زمان هفته ${WEEKDAY_FA[peak.weekday]}‌ها حدود ساعت ${nf.format(peak.hour)} است (${fmt(peak.count)} سفارش).`,
    });
  }
  const stores = d.top_stores || [];
  const total = rev?.value || 0;
  if (stores.length > 1 && total) {
    const lead = stores[0];
    const s = share(lead.revenue, total);
    if (s >= 60)
      out.push({
        id: 'concentration',
        tone: 'wn',
        text: `${lead.name} به‌تنهایی ${fmtPct(s)} فروش را ساخته؛ وابستگی به یک فروشگاه بالاست.`,
      });
  }
  const conv = k.conversion_pct;
  if (conv && d.funnel?.created >= 10 && conv.value < 50) {
    out.push({
      id: 'conversion',
      tone: 'wn',
      text: `فقط ${fmtPct(conv.value)} از سفارش‌های ثبت‌شده به پرداخت رسیده‌اند؛ مسیر پرداخت را بررسی کنید.`,
    });
  }
  if (d.attention_orders > 0) {
    out.push({
      id: 'attention',
      tone: 'bd',
      text: `${fmt(d.attention_orders)} سفارش نیازمند توجه است (بررسی دستی، خطای تحویل، پرداخت ناموفق یا استرداد در انتظار).`,
    });
  }
  if ((k.refunds?.rate_pct || 0) >= 5) {
    out.push({
      id: 'refunds',
      tone: 'wn',
      text: `نرخ استرداد ${fmtPct(k.refunds.rate_pct)} است؛ علت‌ها را بررسی کنید.`,
    });
  }
  for (const p of d.payment_providers || []) {
    if (p.succeeded + p.failed >= 5 && p.success_rate < 80) {
      out.push({
        id: `provider-${p.provider}`,
        tone: 'wn',
        text: `موفقیت ${pick(PROVIDER_LABELS, p.provider)} فقط ${fmtPct(p.success_rate)} است.`,
      });
    }
  }
  if (d.vpn?.expiring_7d > 0) {
    out.push({
      id: 'expiring',
      tone: 'in',
      text: `${fmt(d.vpn.expiring_7d)} اکانت فعال تا ۷ روز آینده منقضی می‌شود؛ فرصت پیام تمدید.`,
    });
  }
  if (d.truncated) {
    out.push({
      id: 'truncated',
      tone: 'wn',
      text: 'حجم داده از سقف گزارش بیشتر بود؛ بازه را کوتاه‌تر کنید تا اعداد کامل باشند.',
    });
  }
  return out;
}

/** Rows for the accessible "table view" of the main chart. */
export function dailyRows(d) {
  if (!d) return [];
  const s = d.series;
  return d.days.map((day, i) => ({
    day,
    revenue: s.revenue[i],
    orders: s.orders[i],
    cash_in: s.cash_in[i],
    new_users: s.new_users[i],
  }));
}

export const browserZone = () => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
};

export function buildQuery({ days, tz, currency, storeId }) {
  const q = new URLSearchParams({ days: String(days), tz });
  if (currency) q.set('currency', currency);
  if (storeId) q.set('store_id', storeId);
  return q.toString();
}
