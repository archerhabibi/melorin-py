// Ticket desk: inbox + conversation side by side, inline editing, internal notes, quick replies.

import { Zap } from 'lucide-react';

export const PRIORITY = { low: ['کم', 'mu'], normal: ['عادی', 'in'], high: ['بالا', 'wn'], urgent: ['فوری', 'bd'] };
export const DEPARTMENTS = [
  ['', 'بدون دسته'],
  ['technical', 'فنی'],
  ['billing', 'مالی'],
  ['sales', 'فروش'],
  ['general', 'عمومی'],
];
export const DEPT_LABEL = Object.fromEntries(DEPARTMENTS);
export const QUICK = [
  ['سلام و احترام', 'سلام، وقت بخیر 🌿\nممنون که با ما در تماس بودید.'],
  ['در حال بررسی', 'درخواست شما در حال بررسی است؛ به‌محض نتیجه، همین‌جا اطلاع می‌دهیم.'],
  ['لطفاً رسید ارسال کنید', 'لطفاً تصویر رسید پرداخت را همراه شمارهٔ پیگیری برای ما ارسال کنید.'],
  [
    'اتصال را بررسی کنید',
    'لطفاً اپلیکیشن را به‌روزرسانی کنید، لینک اشتراک را دوباره وارد کنید و در صورت ادامهٔ مشکل، نوع اینترنت (همراه/ثابت) را اعلام کنید.',
  ],
  ['مشکل برطرف شد', 'مشکل برطرف شد ✅ اگر مورد دیگری بود در خدمتیم. این تیکت بسته می‌شود.'],
];
export const MAX = 10000;
export const STATUS_OPTS = [
  ['open', 'باز'],
  ['answered', 'پاسخ داده شد'],
  ['closed', 'بسته'],
];

export const fromNow = (v) => {
  if (!v) return '';
  const s = (new Date(v).getTime() - Date.now()) / 1000;
  const a = Math.abs(s);
  const rtf = new Intl.RelativeTimeFormat('fa', { numeric: 'auto' });
  if (a < 60) return 'همین الان';
  if (a < 3600) return rtf.format(Math.round(s / 60), 'minute');
  if (a < 86400) return rtf.format(Math.round(s / 3600), 'hour');
  if (a < 86400 * 30) return rtf.format(Math.round(s / 86400), 'day');
  return new Date(v).toLocaleDateString('fa-IR');
};
export const dayKey = (v) => new Date(v).toLocaleDateString('fa-IR', { dateStyle: 'full' });
export const timeOnly = (v) => new Date(v).toLocaleTimeString('fa-IR', { hour: '2-digit', minute: '2-digit' });
export const initials = (s) =>
  String(s || '؟')
    .trim()
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join('') || '؟';
export const needsReply = (t) => t.status === 'open' && t.last_from_staff !== true;

export function PriorityPill({ p }) {
  const [label, tone] = PRIORITY[p] || PRIORITY.normal;
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-bold"
      style={{ background: `var(--${tone}b, var(--mb))`, color: `var(--${tone}, var(--mu))` }}
    >
      {p === 'urgent' && <Zap size={10} />}
      {label}
    </span>
  );
}

/* ───────────────────────────── list column ───────────────────────────── */
