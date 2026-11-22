// ReceiptDuplicatePolicy.tsx — what happens when a customer uploads a receipt PICTURE that another payment already used.
// Works next to the bank-SMS check, not instead of it: the picture fingerprint (sha256 + Telegram file id) is compared at
// upload time. "warn" (default) accepts the receipt and flags it for the reviewer; "block" refuses it before it is stored.
// One control, two API families: the admin console (`/admin/stores/:id`) and the reseller's own store (`/stores/:id/reseller`).
// Both routes are fully typed by the OpenAPI snapshot (paths, body and the `warn | block` response), so there is no casting here.

import { useEffect, useMemo, useState } from 'react';
import { Copy } from 'lucide-react';
import type { components } from '@melorin/api-client';
import { API_BASE, errorMessage, typedClient } from '../../api/api.ts';
import { Segmented } from '../../shared/kit.tsx';
import type { Toast } from '../../shared/types.ts';
import { parseStoreBase } from './receiptHelpers.ts';

type Policy = components['schemas']['ReceiptDupSettingsOut']['policy'];

const OPTIONS: [Policy, string][] = [
  ['warn', 'فقط هشدار'],
  ['block', 'رد کردن'],
];
const HINT: Record<Policy, string> = {
  warn: 'رسید پذیرفته می‌شود و با نشان «تصویر تکراری» برای بازبینی علامت می‌خورد؛ هیچ مشتری درستی ضرر نمی‌کند.',
  block: 'اگر همان تصویر قبلاً برای پرداخت فعال دیگری ثبت شده باشد، بارگذاری رد می‌شود و مشتری باید رسید دیگری بفرستد.',
};

const ADMIN_PATH = '/api/v1/admin/stores/{store_id}/receipt-duplicates/settings' as const;
const RESELLER_PATH = '/api/v1/stores/{store_id}/reseller/receipt-duplicates/settings' as const;

const client = typedClient(API_BASE);
const policyApi = {
  admin: {
    get: (id: string) => client.get(ADMIN_PATH, { params: { path: { store_id: id } } }),
    put: (id: string, policy: Policy) =>
      client.put(ADMIN_PATH, { params: { path: { store_id: id } }, body: { policy } }),
  },
  reseller: {
    get: (id: string) => client.get(RESELLER_PATH, { params: { path: { store_id: id } } }),
    put: (id: string, policy: Policy) =>
      client.put(RESELLER_PATH, { params: { path: { store_id: id } }, body: { policy } }),
  },
};

/** Earlier payments that used the same picture, as stored on a payment (`meta.receipt_duplicate`). */
export type DuplicateInfo = { payments?: { id: string }[]; other_stores?: number } | null | undefined;

/** One short Persian line about the earlier payments that used the same picture (own store by id, others only counted). */
export function duplicateLine(dup: DuplicateInfo): string {
  if (!dup) return '';
  const own = (dup.payments ?? []).map((p) => p.id.slice(0, 8));
  const parts: string[] = [];
  if (own.length) parts.push(own.slice(0, 3).join('، ') + (own.length > 3 ? ` و ${own.length - 3} مورد دیگر` : ''));
  if (dup.other_stores) parts.push(`${dup.other_stores} پرداخت در فروشگاه دیگر`);
  return parts.length ? `همین تصویر قبلاً برای پرداخت ${parts.join(' و ')} ثبت شده است.` : '';
}

/** Mount with `key={base}` so switching store starts from a clean state. Renders nothing for an unknown base or a failed load. */
export default function ReceiptDuplicatePolicy({ toast, base }: { toast: Toast; base?: string }) {
  const target = useMemo(() => parseStoreBase(base), [base]);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!target) return;
    let live = true;
    (async () => {
      try {
        const { data } = await policyApi[target.scope].get(target.storeId);
        if (live && data) setPolicy(data.policy);
      } catch {
        /* transient: the control simply stays hidden */
      }
    })();
    return () => {
      live = false;
    };
  }, [target]);

  const change = async (next: Policy) => {
    if (!target || busy || next === policy) return;
    setBusy(true);
    try {
      const { data, error } = await policyApi[target.scope].put(target.storeId, next);
      if (!data) return toast(errorMessage(error, 'ذخیره ناموفق بود'));
      setPolicy(data.policy);
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
