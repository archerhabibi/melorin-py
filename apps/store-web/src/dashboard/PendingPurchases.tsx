import { useState } from 'react';
import { submitOrder } from '../orderRequest.ts';
import type { PendingOrder } from '../orderRequest.ts';
import { usePendingOrders } from '../usePendingOrders.ts';
import type { Json } from '../types';

export function PendingPurchases({
  coreFetch,
  storeId,
  accountId,
  notify,
  reload,
}: {
  coreFetch?: Json;
  storeId?: string;
  accountId?: string;
  notify?: Json;
  reload?: Json;
}) {
  const pending = usePendingOrders('purchase', storeId, accountId);
  const [busy, setBusy] = useState(false);
  async function retry(attempt: PendingOrder) {
    if (busy) return;
    setBusy(true);
    try {
      const { response } = await submitOrder({
        coreFetch,
        storeId,
        accountId,
        body: attempt.body,
        expectedKey: attempt.key,
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        notify?.(error?.error?.message || 'پیگیری سفارش ناموفق بود');
        return;
      }
      notify?.('سفارش ثبت شد');
      reload?.();
    } catch (error: Json) {
      notify?.(error?.message || 'پیگیری سفارش ناموفق بود');
    } finally {
      pending.refresh();
      setBusy(false);
    }
  }
  if (pending.error) return <p role="status">بررسی درخواست‌های قبلی ممکن نیست؛ ذخیره‌سازی مرورگر را بررسی کنید.</p>;
  if (!pending.attempts.length) return null;
  return (
    <div className="card mb-4 space-y-2">
      <b>پیگیری سفارش قبلی</b>
      <p className="text-sm text-muted">
        نتیجه سفارش قبلی مشخص نیست. اگر ثبت نشده باشد، تلاش مجدد با قیمت فعلی انجام می‌شود.
      </p>
      {pending.attempts.map((attempt, index) => (
        <button
          key={attempt.key}
          disabled={busy || !pending.ready}
          onClick={() => retry(attempt)}
          className="btn-primary w-full"
        >
          تلاش مجدد سفارش قبلی{pending.attempts.length > 1 ? ' ' + (index + 1) : ''}
        </button>
      ))}
    </div>
  );
}
