import { ReactNode } from 'react';
import { AlertTriangle, ClipboardCheck, Package, RotateCcw, Undo2, XCircle } from 'lucide-react';
import { Drawer, tint } from '../../shared/kit.tsx';
import { Badge, dt } from '../../shared/ui.tsx';
import { Facts, money } from '../../shared/dataKit.tsx';
import { Json } from '../../shared/types.ts';
import { RETRYABLE, REVIEWABLE, REFUNDABLE, PROGRESS, OrderFlow, needsAttention } from './OrderParts.tsx';

export function OrderDrawer({
  o,
  busy,
  customer,
  email,
  store,
  onClose,
  act,
  attach,
}: {
  attach?: ReactNode;
  o?: Json;
  busy?: Json;
  customer?: Json;
  email?: Json;
  store?: Json;
  onClose?: Json;
  act?: Json;
}) {
  const canRetry = RETRYABLE.includes(o.status);
  const canReview = REVIEWABLE.includes(o.status);
  const canRefund = REFUNDABLE.includes(o.status);
  const none = !canRetry && !canReview && !canRefund;
  return (
    <Drawer
      title={`سفارش ${o.number}`}
      subtitle={`${store} · ${dt(o.created_at)}`}
      icon={
        <span className="tile h-10 w-10" style={tint(needsAttention(o) ? 'wn' : 'in')}>
          <Package size={19} />
        </span>
      }
      busy={busy}
      onClose={onClose}
      footer={
        <>
          {canRetry && (
            <button className="btn !py-2 !text-sm" disabled={busy} onClick={() => act(o, 'retry', 'تلاش مجدد')}>
              <RotateCcw size={14} />
              تلاش مجدد
            </button>
          )}
          {canReview && (
            <button
              className="btn btn-g !py-2 !text-sm"
              disabled={busy}
              onClick={() => act(o, 'manual-review', 'بررسی دستی')}
            >
              <ClipboardCheck size={14} />
              ارجاع به بررسی دستی
            </button>
          )}
        </>
      }
      danger={
        canRefund && (
          <button
            className="btn btn-g btn-d !py-2 !text-sm"
            disabled={busy}
            onClick={() => act(o, 'refund', 'استرداد')}
          >
            <Undo2 size={14} />
            استرداد
          </button>
        )
      }
    >
      <div className="card flex flex-wrap items-center justify-between gap-3 p-4">
        <div>
          <p className="text-xs text-[var(--mu)]">مبلغ سفارش</p>
          <p className="num mt-1 text-2xl font-extrabold">{money(o.total, o.currency)}</p>
        </div>
        <Badge s={o.status} />
      </div>
      {PROGRESS[o.status] && (
        <section className="card p-4">
          <h3 className="mb-3 text-[13px] font-extrabold">مسیر سفارش</h3>
          <OrderFlow status={o.status} />
        </section>
      )}
      {needsAttention(o) && (
        <p className="flex items-start gap-2 rounded-xl bg-[var(--wnb)] p-3 text-xs leading-6 text-[var(--wn)]">
          <AlertTriangle size={15} className="mt-0.5 shrink-0" />
          این سفارش نیاز به بررسی دارد. از دکمه‌های پایین برای تلاش مجدد، ارجاع به بررسی دستی یا استرداد استفاده کنید.
        </p>
      )}
      {none && (
        <p className="flex items-start gap-2 rounded-xl bg-[var(--mb)] p-3 text-xs leading-6 text-[var(--mu)]">
          <XCircle size={15} className="mt-0.5 shrink-0" />
          در وضعیت فعلی، اقدام دستی برای این سفارش مجاز نیست.
        </p>
      )}
      {attach}
      <Facts
        items={[
          { label: 'شماره سفارش', value: o.number, ltr: true, copy: true },
          { label: 'مشتری', value: customer },
          { label: 'ایمیل', value: email, ltr: true, copy: true },
          { label: 'فروشگاه', value: store },
          { label: 'تاریخ ثبت', value: dt(o.created_at) },
          { label: 'شناسه سفارش', value: o.id, ltr: true, copy: true },
        ]}
      />
    </Drawer>
  );
}
