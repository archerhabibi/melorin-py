// ReceiptDuplicatePolicy.tsx — what happens when a customer uploads a receipt PICTURE that another payment already used.
// Works next to the bank-SMS check, not instead of it: the picture fingerprint (sha256 + Telegram file id) is compared at
// upload time. "warn" (default) accepts the receipt and flags it for the reviewer; "block" refuses it before it is stored.
// The same relative path serves the admin (`/admin/stores/:id`) and the reseller (`/stores/:id/reseller`) base.

import { useCallback, useEffect, useState } from 'react';
import { Copy } from 'lucide-react';
import { Segmented, errText } from './kit.tsx';
import type { CallFn, Json, Rec, Toast } from './types.ts';

const OPTIONS = [
  ['warn', 'فقط هشدار'],
  ['block', 'رد کردن'],
];
const HINT: Rec = {
  warn: 'رسید پذیرفته می‌شود و با نشان «تصویر تکراری» برای بازبینی علامت می‌خورد؛ هیچ مشتری درستی ضرر نمی‌کند.',
  block: 'اگر همان تصویر قبلاً برای پرداخت فعال دیگری ثبت شده باشد، بارگذاری رد می‌شود و مشتری باید رسید دیگری بفرستد.',
};

/** One short Persian line about the earlier payments that used the same picture (own store by id, others only counted). */
export function duplicateLine(dup: Json) {
  if (!dup) return '';
  const own = (dup.payments || []).map((p: Json) => p.id.slice(0, 8));
  const parts: Json[] = [];
  if (own.length) parts.push(own.slice(0, 3).join('، ') + (own.length > 3 ? ` و ${own.length - 3} مورد دیگر` : ''));
  if (dup.other_stores) parts.push(`${dup.other_stores} پرداخت در فروشگاه دیگر`);
  return parts.length ? `همین تصویر قبلاً برای پرداخت ${parts.join(' و ')} ثبت شده است.` : '';
}

export default function ReceiptDuplicatePolicy({ call, toast, base }: { call: CallFn; toast: Toast; base?: string }) {
  const [policy, setPolicy] = useState<Json>(null);
  const [busy, setBusy] = useState(false);
  const url = `${base}/receipt-duplicates/settings`;

  const load = useCallback(async () => {
    try {
      const r = await call(url);
      if (!r.ok) return; // an older server without this feature: show nothing
      const d = await r.json();
      if (d?.policy) setPolicy(d.policy);
    } catch {
      /* transient */
    }
  }, [call, url]);
  useEffect(() => {
    load();
  }, [load]);

  const change = async (next: Json) => {
    if (busy || next === policy) return;
    setBusy(true);
    try {
      const r = await call(url, { method: 'PUT', body: JSON.stringify({ policy: next }) });
      if (!r.ok) return toast(await errText(r, 'ذخیره ناموفق بود'));
      setPolicy((await r.json()).policy);
      toast('تنظیم رسید تکراری ذخیره شد');
    } catch {
      toast('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy(false);
    }
  };

  if (!policy) return null;
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[var(--ln)] p-3">
      <div className="min-w-0 space-y-1">
        <div className="flex items-center gap-2 text-xs font-extrabold">
          <Copy size={14} /> رسید تکراری (تصویر مشابه)
        </div>
        <p className="text-[11px] leading-5 text-[var(--mu)]">{HINT[policy]}</p>
      </div>
      <Segmented value={policy} onChange={change} options={OPTIONS} label="رفتار در برابر تصویر رسید تکراری" />
    </div>
  );
}
