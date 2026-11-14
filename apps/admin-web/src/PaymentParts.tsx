// Payments screen — review queue, KPIs, filters, detail drawer and gateway settings.
// Data comes only from GET /api/v1/admin/payments (+ /settings); actions use the existing
// /review, /refund and /receipt endpoints, so no backend change is required.
import { useEffect, useState } from 'react';
import { Check, ChevronDown, Copy, Receipt, Settings2, ShieldAlert, Undo2, X, XCircle } from 'lucide-react';

import { Drawer, Field, Section, Switch, num, tint } from './kit.tsx';
import { Badge, dt, sid } from './ui.tsx';

import { prov, reviewable, refundable, ago, copy, ProviderChip, Amount } from './paymentsShared.tsx';
import type { CallFn, Json, Toast } from './types.ts';

export function RowActions({ p, busy, on, compact = false }: { p?: Json; busy?: Json; on?: Json; compact?: Json }) {
  const b = compact ? '!px-2' : '';
  return (
    <div role="presentation" className="flex items-center justify-end gap-1.5" onClick={(e) => e.stopPropagation()}>
      {p.has_receipt && (
        <button className={`btn btn-g ${b}`} title="مشاهده رسید" aria-label="مشاهده رسید" onClick={() => on.receipt(p)}>
          <Receipt size={14} />
          {!compact && 'رسید'}
        </button>
      )}
      {reviewable(p) && (
        <>
          <button
            disabled={busy}
            className={`btn btn-g pay-ok ${b}`}
            title="تأیید پرداخت"
            aria-label="تأیید پرداخت"
            onClick={() => on.approve(p)}
          >
            <Check size={14} />
            {!compact && 'تأیید'}
          </button>
          <button
            disabled={busy}
            className={`btn btn-g btn-d ${b}`}
            title="رد پرداخت"
            aria-label="رد پرداخت"
            onClick={() => on.reject(p)}
          >
            <X size={14} />
            {!compact && 'رد'}
          </button>
        </>
      )}
      {refundable(p) && (
        <button
          disabled={busy}
          className={`btn btn-g btn-d ${b}`}
          title="استرداد"
          aria-label="استرداد"
          onClick={() => on.refund(p)}
        >
          <Undo2 size={14} />
          {!compact && 'استرداد'}
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- review queue
export function Queue({
  items,
  busy,
  on,
  seeAll,
  total,
}: {
  items?: Json;
  busy?: Json;
  on?: Json;
  seeAll?: Json;
  total?: Json;
}) {
  if (!items.length) return null;
  return (
    <section className="pay-queue rise">
      <div className="flex items-center justify-between gap-3 px-5 pt-4">
        <div className="flex items-center gap-2.5">
          <span className="tile relative h-10 w-10" style={tint('wn')}>
            <ShieldAlert size={18} />
            <span className="pv-ping absolute -left-0.5 -top-0.5 h-2.5 w-2.5 rounded-full bg-[var(--wn)]" />
          </span>
          <div>
            <h3 className="font-extrabold">صف بررسی رسیدها</h3>
            <p className="text-xs text-[var(--mu)]">{num(total)} پرداخت منتظر تصمیم شماست</p>
          </div>
        </div>
        {total > items.length && (
          <button className="btn btn-g" onClick={seeAll}>
            مشاهده همه ({num(total)})
          </button>
        )}
      </div>
      <div className="pay-queue-row">
        {items.map((p: Json) => (
          <article key={p.id} className="pay-qcard">
            <div className="flex items-start justify-between gap-2">
              <ProviderChip k={p.provider} />
              <span className="text-[11px] text-[var(--mu)]">{ago(p.created_at)}</span>
            </div>
            <div className="mt-3">
              <Amount p={p} big />
            </div>
            <div className="mt-1 text-[11px] text-[var(--mu)]">
              کاربر{' '}
              <span dir="ltr" className="font-mono">
                {sid(p.user_id)}
              </span>
            </div>
            <div className="mt-4 grid grid-cols-[auto_1fr_auto] gap-1.5">
              <button
                className="btn btn-g !px-2.5"
                aria-label="مشاهده رسید"
                title="مشاهده رسید"
                onClick={() => on.receipt(p)}
              >
                <Receipt size={15} />
              </button>
              <button disabled={busy === p.id} className="btn" onClick={() => on.approve(p)}>
                <Check size={15} />
                تأیید
              </button>
              <button
                disabled={busy === p.id}
                className="btn btn-g btn-d !px-2.5"
                aria-label="رد پرداخت"
                title="رد پرداخت"
                onClick={() => on.reject(p)}
              >
                <X size={15} />
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- detail drawer (shared kit Drawer)
export function PaymentDrawer({
  p,
  busy,
  on,
  onClose,
  toast,
  call,
}: {
  p?: Json;
  busy?: Json;
  on?: Json;
  onClose?: Json;
  toast: Toast;
  call: CallFn;
}) {
  const [img, setImg] = useState<Json>(null);
  const [loadingImg, setLoadingImg] = useState(false);
  useEffect(() => {
    setImg(null);
  }, [p.id]);
  useEffect(
    () => () => {
      if (img) URL.revokeObjectURL(img);
    },
    [img],
  );
  const preview = async () => {
    setLoadingImg(true);
    try {
      const r = await call(`/api/v1/admin/payments/${p.id}/receipt`);
      if (!r.ok) return toast('نمایش رسید ناموفق بود');
      const blob = await r.blob();
      if (blob.type.startsWith('image/')) setImg(URL.createObjectURL(blob));
      else {
        const u = URL.createObjectURL(blob);
        window.open(u, '_blank', 'noopener');
        setTimeout(() => URL.revokeObjectURL(u), 60000);
      }
    } catch {
      toast('ارتباط با سرور برقرار نشد');
    } finally {
      setLoadingImg(false);
    }
  };
  const ids = [
    ['شناسه پرداخت', p.id],
    ['شناسه کاربر', p.user_id],
    ['شناسه فروشگاه', p.store_id],
  ];
  const footer = (
    <>
      {reviewable(p) && (
        <>
          <button disabled={busy} className="btn !py-2 !text-sm" onClick={() => on.approve(p)}>
            <Check size={15} />
            تأیید پرداخت
          </button>
          <button disabled={busy} className="btn btn-g btn-d !py-2 !text-sm" onClick={() => on.reject(p)}>
            <XCircle size={15} />
            رد
          </button>
        </>
      )}
      {refundable(p) && (
        <button disabled={busy} className="btn btn-g btn-d !py-2 !text-sm" onClick={() => on.refund(p)}>
          <Undo2 size={15} />
          استرداد پرداخت
        </button>
      )}
    </>
  );
  return (
    <Drawer
      title="جزئیات پرداخت"
      subtitle={`${prov(p.provider).label} · ${sid(p.id)}`}
      busy={busy}
      onClose={onClose}
      footer={footer}
      icon={
        <span className="tile h-11 w-11" style={tint('in')}>
          <Receipt size={19} />
        </span>
      }
    >
      <div className="card p-5 text-center">
        <Amount p={p} big />
        <div className="mt-3 flex items-center justify-center gap-2">
          <Badge s={p.status} />
          <span className="text-xs text-[var(--mu)]">{ago(p.created_at)}</span>
        </div>
      </div>
      <Section title="اطلاعات تراکنش">
        <dl className="divide-y divide-[var(--ln)] text-sm">
          <div className="flex items-center justify-between gap-3 pb-3">
            <dt className="text-[var(--mu)]">درگاه</dt>
            <dd>
              <ProviderChip k={p.provider} size={14} />
            </dd>
          </div>
          <div className="flex items-center justify-between gap-3 py-3">
            <dt className="text-[var(--mu)]">ثبت در</dt>
            <dd className="font-bold">{dt(p.created_at)}</dd>
          </div>
          {ids.map(([k, v], i) => (
            <div
              key={k}
              className={`flex items-center justify-between gap-3 ${i === ids.length - 1 ? 'pt-3' : 'py-3'}`}
            >
              <dt className="text-[var(--mu)]">{k}</dt>
              <dd className="flex min-w-0 items-center gap-1.5">
                <code dir="ltr" className="truncate text-xs">
                  {sid(v)}
                </code>
                <button
                  className="rounded-md p-1 text-[var(--mu)] hover:bg-[var(--mb)]"
                  aria-label={`کپی ${k}`}
                  onClick={() => copy(v, toast)}
                >
                  <Copy size={13} />
                </button>
              </dd>
            </div>
          ))}
        </dl>
      </Section>
      <Section title="رسید پرداخت">
        {!p.has_receipt && (
          <p className="rounded-xl border border-dashed border-[var(--ln)] p-5 text-center text-xs text-[var(--mu)]">
            رسیدی برای این پرداخت ثبت نشده است.
          </p>
        )}
        {p.has_receipt && !img && (
          <button className="btn btn-g" disabled={loadingImg} onClick={preview}>
            <Receipt size={14} />
            {loadingImg ? 'در حال دریافت…' : 'نمایش رسید'}
          </button>
        )}
        {img && (
          <img
            src={img}
            alt="رسید پرداخت"
            className="max-h-96 w-full rounded-xl border border-[var(--ln)] bg-[var(--mb)] object-contain"
          />
        )}
      </Section>
    </Drawer>
  );
}

// ---------------------------------------------------------------- gateway settings
export const maskCard = (n: Json) => {
  const d = String(n || '').replace(/\D/g, '');
  return d.length >= 8 ? `${d.slice(0, 4)} •••• •••• ${d.slice(-4)}` : '';
};

export function GatewaySettings({ obj, save }: { obj?: Json; save?: Json }) {
  const [open, setOpen] = useState(false);
  const card = obj.manual_card || {};
  const zp = obj.zarinpal || {};
  const [c, setC] = useState({ card_number: '', holder: '', bank: '', ...card });
  const [z, setZ] = useState({ merchant_id: '', sandbox: false, ...zp });
  useEffect(() => setC({ card_number: '', holder: '', bank: '', ...(obj.manual_card || {}) }), [obj]);
  useEffect(() => setZ({ merchant_id: '', sandbox: false, ...(obj.zarinpal || {}) }), [obj]);
  const cardOk = !!(card.card_number && card.holder);
  const zpOk = !!zp.merchant_id;
  return (
    <section className="card overflow-hidden">
      <button
        className="flex w-full items-center justify-between gap-3 px-5 py-4 text-right"
        aria-expanded={open}
        onClick={() => setOpen((x) => !x)}
      >
        <span className="flex items-center gap-3">
          <span className="tile h-10 w-10 bg-[var(--mb)] text-[var(--mu)]">
            <Settings2 size={18} />
          </span>
          <span>
            <span className="block font-extrabold">درگاه‌ها و روش‌های دریافت</span>
            <span className="block text-xs text-[var(--mu)]">کارت‌به‌کارت و زرین‌پال فروشگاه اصلی</span>
          </span>
        </span>
        <span className="flex items-center gap-2">
          <span className="hidden gap-1.5 sm:flex">
            <span className={`badge ${cardOk ? 'b-ok' : 'b-mu'}`}>{cardOk ? 'کارت تنظیم شد' : 'کارت: تنظیم نشده'}</span>
            <span className={`badge ${zpOk ? 'b-ok' : 'b-mu'}`}>{zpOk ? 'زرین‌پال فعال' : 'زرین‌پال: تنظیم نشده'}</span>
          </span>
          <ChevronDown size={18} className={`text-[var(--mu)] transition-transform ${open ? 'rotate-180' : ''}`} />
        </span>
      </button>
      {open && (
        <div className="grid gap-4 border-t border-[var(--ln)] p-5 md:grid-cols-2">
          <div className="rounded-2xl border border-[var(--ln)] p-4">
            <div className="mb-3 flex items-center justify-between">
              <h4 className="font-bold">کارت‌به‌کارت</h4>
              {maskCard(card.card_number) && (
                <span dir="ltr" className="font-mono text-[11px] text-[var(--mu)]">
                  {maskCard(card.card_number)}
                </span>
              )}
            </div>
            <div className="grid gap-3">
              <Field label="شماره کارت">
                <input
                  dir="ltr"
                  inputMode="numeric"
                  className="inp"
                  value={c.card_number}
                  onChange={(e) => setC({ ...c, card_number: e.target.value })}
                />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="نام صاحب کارت">
                  <input className="inp" value={c.holder} onChange={(e) => setC({ ...c, holder: e.target.value })} />
                </Field>
                <Field label="بانک">
                  <input className="inp" value={c.bank} onChange={(e) => setC({ ...c, bank: e.target.value })} />
                </Field>
              </div>
            </div>
            <button
              className="btn mt-4"
              disabled={!c.card_number.trim() || !c.holder.trim()}
              onClick={() => save('manual_card', c)}
            >
              ذخیره اطلاعات کارت
            </button>
          </div>
          <div className="rounded-2xl border border-[var(--ln)] p-4">
            <div className="mb-3 flex items-center justify-between">
              <h4 className="font-bold">زرین‌پال</h4>
              {z.sandbox && <span className="badge b-in">Sandbox</span>}
            </div>
            <div className="grid gap-3">
              <Field label="Merchant ID">
                <input
                  dir="ltr"
                  className="inp font-mono text-xs"
                  value={z.merchant_id}
                  onChange={(e) => setZ({ ...z, merchant_id: e.target.value })}
                />
              </Field>
              <div className="flex items-center justify-between rounded-xl bg-[var(--sf2)] px-3.5 py-3 text-sm font-bold">
                حالت آزمایشی (Sandbox)
                <Switch checked={!!z.sandbox} onChange={(v: Json) => setZ({ ...z, sandbox: v })} label="حالت Sandbox" />
              </div>
            </div>
            <button className="btn mt-4" disabled={!z.merchant_id.trim()} onClick={() => save('zarinpal', z)}>
              ذخیره تنظیمات زرین‌پال
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- main view
