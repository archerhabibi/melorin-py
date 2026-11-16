import type { ReactNode } from 'react';
import { AlertTriangle, Clock, Copy, Hourglass, ImageIcon } from 'lucide-react';
import { num } from '../../shared/kit.tsx';
import { dt } from '../../shared/ui.tsx';
import { duplicateLine } from './ReceiptDuplicatePolicy.tsx';
import type { Json } from '../../shared/types.ts';
import { CUR, clock, ago } from './receiptHelpers';

export function Facts({ r }: { r?: Json }) {
  if (!r) return <span className="text-[11px] text-[var(--mu)]">اطلاعاتی از روی رسید خوانده نشده</span>;
  const rows = [
    ['مبلغ رسید', r.amount_rial ? `${num(r.amount_rial)} ریال` : null],
    ['زمان', r.paid_at ? dt(r.paid_at) : null],
    ['کارت مبدأ', r.source_card_last4 ? `…${r.source_card_last4}` : null],
    ['مرجع', r.reference],
  ].filter(([, v]) => v);
  if (!rows.length) return <span className="text-[11px] text-[var(--mu)]">رسید خوانده نشد (بررسی چشمی لازم است)</span>;
  return (
    <span className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-[var(--mu)]">
      {rows.map(([k, v]) => (
        <span key={k}>
          {k}: <b dir="ltr">{v}</b>
        </span>
      ))}
    </span>
  );
}

export function Row({
  item,
  tone,
  now,
  minutes,
  children,
  onReceipt,
}: {
  item?: Json;
  tone?: Json;
  now?: Json;
  minutes?: Json;
  children?: ReactNode;
  onReceipt?: Json;
}) {
  const left = item.auto_approve_at ? (new Date(item.auto_approve_at).getTime() - now) / 1000 : null;
  const total = (minutes || 5) * 60;
  const pct = left == null ? 0 : Math.min(100, Math.max(0, ((total - left) / total) * 100));
  return (
    <li className="rounded-xl border p-3" style={{ borderColor: `var(--${tone}, var(--ln))` }}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <b className="text-sm">
              {num(item.amount)} {CUR[item.currency] || item.currency}
            </b>
            {item.block_text && (
              <span className="badge b-wn" title={item.block_text}>
                <AlertTriangle size={11} /> تأیید موقت نمی‌شود
              </span>
            )}
            {item.duplicate && (
              <span className="badge b-wn" title={duplicateLine(item.duplicate)}>
                <Copy size={11} /> تصویر تکراری
              </span>
            )}
            {item.shortfall ? <span className="badge b-bd">کسری کیف پول: {num(item.shortfall)}</span> : null}
          </div>
          {item.block_text && <div className="text-[11px] text-[var(--wn)]">{item.block_text}</div>}
          {item.duplicate && <div className="text-[11px] text-[var(--wn)]">{duplicateLine(item.duplicate)}</div>}
          <Facts r={item.receipt_read} />
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {onReceipt && (
            <button className="btn btn-g !py-1.5" onClick={() => onReceipt(item)} aria-label="مشاهده تصویر رسید">
              <ImageIcon size={14} /> رسید
            </button>
          )}
          {children}
        </div>
      </div>
      {left != null && !item.block && (
        <div className="mt-2.5">
          <div className="mb-1 flex items-center justify-between text-[11px] text-[var(--mu)]">
            <span className="flex items-center gap-1">
              <Hourglass size={12} /> {left > 0 ? 'تا تأیید موقت' : 'در حال تأیید موقت…'}
            </span>
            <b dir="ltr" aria-live="off">
              {clock(left)}
            </b>
          </div>
          <div
            className="h-1.5 overflow-hidden rounded-full bg-[var(--bg2)]"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(pct)}
            aria-label="زمان باقی‌مانده تا تأیید موقت"
          >
            <div
              className="h-full rounded-full bg-[var(--wn)] transition-[width] duration-1000"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
      )}
      {item.credited_at && (
        <div className="mt-1.5 flex items-center gap-1 text-[11px] text-[var(--mu)]">
          <Clock size={12} /> شارژ موقت: {ago((now - new Date(item.credited_at).getTime()) / 1000)}
        </div>
      )}
    </li>
  );
}

/** ``base`` = store API root, e.g. ``/api/v1/admin/stores/<id>`` or ``/api/v1/stores/<id>/reseller``. */
