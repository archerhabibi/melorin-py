import { useState } from 'react';
import { errText } from '../../kit.tsx';
import type { CallFn, Json, Toast } from '../../types.ts';

// key, label, hint, adminOnly - the same six fields as Core's PROFILE_FIELDS (a reseller may only ask for the first four)
export const FIELDS: [string, string, string, boolean][] = [
  ['profile_title', 'عنوان پروفایل', 'نام نمایشی ادمین در صفحهٔ اشتراک مشتری.', false],
  ['support_url', 'لینک پشتیبانی', 'آدرس https://… یا tg://… ؛ خالی‌گذاشتن آن را پاک می‌کند.', false],
  ['telegram_id', 'آیدی عددی تلگرام', 'فقط عدد. پس از ثبت فقط قابل تغییر است و پاک نمی‌شود.', false],
  [
    'discord_webhook',
    'وبهوک دیسکورد',
    'فقط آدرس https://discord.com/api/webhooks/… ؛ خالی‌گذاشتن آن را پاک می‌کند.',
    false,
  ],
  ['sub_domain', 'دامنهٔ اشتراک', 'فقط ادمین. آدرس لینک‌های اشتراک مشتریان را عوض می‌کند.', true],
  ['note', 'یادداشت داخلی', 'فقط ادمین. هرگز به نماینده نمایش داده نمی‌شود.', true],
];
export const LABEL = Object.fromEntries(FIELDS.map(([k, l]) => [k, l]));
export const shown = (v: Json) => (v === undefined || v === null || v === '' ? '—' : String(v));
export const ltr = (v: Json) => (
  <span dir="ltr" className="latin break-all text-xs">
    {shown(v)}
  </span>
);

export const STATUS_PILLS = [
  ['all', 'همه'],
  ['active', 'فعال'],
  ['pending', 'در حال راه‌اندازی'],
  ['error', 'خطا'],
  ['unsynced', 'پروفایل همگام نشده'],
];
export const REQUEST_PILLS = [
  ['pending', 'در انتظار'],
  ['applied', 'اعمال‌شده'],
  ['rejected', 'رد‌شده'],
  ['cancelled', 'لغو‌شده'],
  ['all', 'همه'],
];

export const KindBadge = ({ kind }: { kind?: Json }) =>
  kind === 'main' ? <span className="badge b-in">فروشگاه اصلی</span> : <span className="badge b-mu">نماینده</span>;

/** POST/PATCH helper shared by both drawers: resolves to the parsed body, or null after putting the reason in `setError`. */
export function useCall(call: CallFn, toast: Toast) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const run = async (path: string, method: string, body?: Json, okMsg?: string) => {
    setBusy(true);
    setError('');
    try {
      const r = await call(path, { method, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
      if (!r.ok) {
        setError(await errText(r, 'عملیات ناموفق بود'));
        return null;
      }
      const d = await r.json().catch(() => ({}));
      if (okMsg) toast(okMsg);
      return d;
    } catch {
      setError('ارتباط با سرور برقرار نشد');
      return null;
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, setError, run };
}
