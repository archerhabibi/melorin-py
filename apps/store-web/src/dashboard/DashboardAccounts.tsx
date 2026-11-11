import { useEffect, useState } from 'react';
import {
  Bell,
  Gauge,
  KeyRound,
  LifeBuoy,
  Package,
  Wallet as WalletIcon,
  RefreshCw,
  Undo2,
  Loader2,
  X,
} from 'lucide-react';
import AccountInquiry from '../AccountInquiry.tsx';
import { Empty, Loading, StatusBadge, fa, fd } from '../ui.tsx';
import { msgOf } from './DashboardTickets.tsx';
import type { Json } from '../types';

export const J = { 'Content-Type': 'application/json' };
export const tabs = [
  ['orders', 'سفارش‌ها', Package],
  ['vpn', 'اکانت‌های VPN', Gauge],
  ['wallet', 'کیف پول', WalletIcon],
  ['tickets', 'تیکت‌ها', LifeBuoy],
  ['notifications', 'اعلان‌ها', Bell],
  ['profile', 'پروفایل و امنیت', KeyRound],
];
export const card = 'card';
export const btn = 'btn-primary';
export const inp = 'input';

export function Orders({ orders }: { orders?: Json }) {
  if (!orders.length) return <Empty text="هنوز سفارشی ثبت نشده است." />;
  return (
    <div className="space-y-3">
      {orders.map((o: Json) => (
        <div key={o.id} className={`${card} flex flex-wrap items-center justify-between gap-3`}>
          <div>
            <div className="latin font-extrabold">{o.number}</div>
            <div className="mt-1 text-xs text-muted">{fd(o.created_at)}</div>
          </div>
          <div className="font-bold">
            {fa(o.total)} {o.currency}
          </div>
          <StatusBadge status={o.status} />
        </div>
      ))}
    </div>
  );
}

function Renew({
  account,
  coreFetch,
  storeId,
  notify,
  reload,
  onClose,
}: {
  account?: Json;
  coreFetch?: Json;
  storeId?: Json;
  notify?: Json;
  reload?: Json;
  onClose?: Json;
}) {
  // The core decides everything (10-day window, package, current price); this card only shows its answer and pays.
  const [info, setInfo] = useState<Json>(null);
  const [quote, setQuote] = useState<Json>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const r = await coreFetch(`/api/v1/stores/${storeId}/accounts/${account.id}/renewal`);
        if (!r.ok) throw r;
        const d = await r.json();
        if (!live) return;
        setInfo(d);
        if (!d.renewable) return;
        const q = await coreFetch(`/api/v1/stores/${storeId}/checkout/quote`, {
          method: 'POST',
          headers: J,
          body: JSON.stringify({ product_id: d.package.product_id, vpn_account_id: account.id }),
        });
        if (!q.ok) return notify(await msgOf(q, 'پیش‌فاکتور دریافت نشد'));
        if (live) setQuote(await q.json());
      } catch (r: Json) {
        if (live) {
          setInfo({
            renewable: false,
            message: r?.json ? await msgOf(r, 'اطلاعات تمدید دریافت نشد') : 'اطلاعات تمدید دریافت نشد',
          });
        }
      }
    })();
    return () => {
      live = false;
    };
  }, [account.id, coreFetch, notify, storeId]);
  async function buy() {
    setBusy(true);
    try {
      const r = await coreFetch(`/api/v1/stores/${storeId}/orders`, {
        method: 'POST',
        headers: { ...J, 'Idempotency-Key': `web-renew-${crypto.randomUUID()}` },
        body: JSON.stringify({
          product_id: info.package.product_id,
          payment_method: 'wallet',
          kind: 'renewal',
          vpn_account_id: account.id,
        }),
      });
      if (!r.ok) return notify(await msgOf(r, 'تمدید ناموفق بود'));
      notify('تمدید ثبت شد');
      reload?.();
      onClose();
    } finally {
      setBusy(false);
    }
  }
  const after = quote?.renewal || info?.after;
  return (
    <div className="mt-4 rounded-xl bg-surface2 p-3 text-sm">
      <div className="flex items-center justify-between">
        <b>تمدید اکانت</b>
        <button onClick={onClose} aria-label="بستن" className="text-muted">
          <X size={16} />
        </button>
      </div>
      {info === null ? (
        <Loading rows={1} />
      ) : !info.renewable ? (
        <p className="mt-2 text-xs text-muted">{info.message || 'این اکانت قابل تمدید نیست.'}</p>
      ) : (
        <div className="mt-2 space-y-1">
          <div>
            <b>{info.package.name}</b>
          </div>
          {after && (
            <div className="text-xs text-muted">
              پس از تمدید: {fa(after.duration_days)} روز ·{' '}
              {after.traffic_gb ? `${fa(after.traffic_gb)} گیگ` : 'نامحدود'} (مثل یک اکانت جدید همین پکیج)
            </div>
          )}
          {after?.remaining_days_replaced > 0 && (
            <div className="text-xs text-muted">
              {fa(after.remaining_days_replaced)} روز باقی‌مانده فعلی جایگزین می‌شود و به آن اضافه نمی‌شود.
            </div>
          )}
        </div>
      )}
      {quote && (
        <div className="mt-3 flex items-center justify-between gap-3 border-t border-line pt-3">
          <span>
            مبلغ نهایی:{' '}
            <b>
              {fa(quote.total)} {quote.currency}
            </b>
            {!quote.sufficient_funds && <span className="mr-2 text-xs text-danger">موجودی کافی نیست</span>}
          </span>
          <button disabled={busy || !quote.sufficient_funds} onClick={buy} className="btn-primary !px-4 !py-2 text-xs">
            پرداخت از کیف پول و تمدید
          </button>
        </div>
      )}
    </div>
  );
}

// مرجوعی: Core decides (volume account, <= 3 days, <= 5 % used, 3 per day); the card only asks, confirms and shows Core's words.
function ReturnAccount({
  account,
  coreFetch,
  storeId,
  notify,
  reload,
  onClose,
}: {
  account?: Json;
  coreFetch?: Json;
  storeId?: Json;
  notify?: Json;
  reload?: Json;
  onClose?: Json;
}) {
  const [busy, setBusy] = useState(false);
  const [rules, setRules] = useState('');
  useEffect(() => {
    coreFetch(`/api/v1/stores/${storeId}/vpn-accounts/return-rules`)
      .then((r: Json) => (r.ok ? r.json() : null))
      .then((d: Json) => d && setRules(d.text))
      .catch(() => {});
  }, [coreFetch, storeId]);
  const go = async () => {
    setBusy(true);
    try {
      const r = await coreFetch(`/api/v1/stores/${storeId}/vpn-accounts/${account.id}/return`, { method: 'POST' });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d?.error?.message || 'مرجوعی انجام نشد');
      notify?.(d.message || 'اکانت مرجوع شد');
      onClose();
      reload?.();
    } catch (e: Json) {
      notify?.(e.message || 'مرجوعی انجام نشد');
    }
    setBusy(false);
  };
  return (
    <div className="mt-2 rounded-xl bg-surface2 p-3 text-xs leading-6" role="alertdialog" aria-label="مرجوعی اکانت">
      <p className="font-bold text-ink">اکانت «{account.username}» مرجوع شود؟</p>
      <p className="mt-1 text-muted">
        اکانت بلافاصله غیرفعال می‌شود و مبلغ پرداختی به کیف پول همین فروشگاه برمی‌گردد. این کار قابل بازگشت نیست.
      </p>
      {rules && <p className="mt-1 text-muted">{rules}</p>}
      <div className="mt-3 flex gap-2">
        <button onClick={go} disabled={busy} className="btn-primary flex-1 !py-2 text-xs">
          {busy ? <Loader2 size={14} className="animate-spin" /> : <Undo2 size={14} />}بله، مرجوع کن
        </button>
        <button onClick={onClose} disabled={busy} className="btn-soft flex-1 !py-2 text-xs">
          انصراف
        </button>
      </div>
    </div>
  );
}

export function Vpn({
  coreFetch,
  storeId,
  notify,
  reload,
}: {
  coreFetch?: Json;
  storeId?: Json;
  notify?: Json;
  reload?: Json;
}) {
  const [renew, setRenew] = useState<Json>(null);
  const [giveBack, setGiveBack] = useState<Json>(null);
  const [tick, setTick] = useState(0);
  return (
    <AccountInquiry
      coreFetch={coreFetch}
      base={`/api/v1/stores/${storeId}/vpn-accounts`}
      notify={notify}
      reloadKey={tick}
      emptyText="اکانتی ندارید. از بخش سرویس‌ها خرید کنید."
      emptyAction={
        <a href="#plans" className="btn-primary mt-5">
          دیدن سرویس‌ها
        </a>
      }
      renderExtra={(a: Json) => (
        <>
          {a.can_renew ? (
            <button onClick={() => setRenew(renew === a.id ? null : a.id)} className="btn-soft mt-2 w-full">
              <RefreshCw size={16} />
              تمدید
            </button>
          ) : (
            a.renew_note && !a.is_test && <p className="mt-2 text-xs text-muted">{a.renew_note}</p>
          )}
          {!a.is_test && (
            <>
              <button
                onClick={() =>
                  a.can_return
                    ? setGiveBack(giveBack === a.id ? null : a.id)
                    : notify?.(a.return_note || 'این اکانت قابل مرجوع نیست.')
                }
                aria-disabled={!a.can_return || undefined}
                className={`btn-soft mt-2 w-full ${a.can_return ? '' : 'opacity-60'}`}
              >
                <Undo2 size={16} />
                مرجوعی اکانت
              </button>
              {!a.can_return && a.return_note && <p className="mt-1 text-xs text-muted">{a.return_note}</p>}
            </>
          )}
          {giveBack === a.id && (
            <ReturnAccount
              account={a}
              coreFetch={coreFetch}
              storeId={storeId}
              notify={notify}
              reload={() => {
                reload?.();
                setTick((t) => t + 1);
              }}
              onClose={() => setGiveBack(null)}
            />
          )}
          {renew === a.id && (
            <Renew
              account={a}
              coreFetch={coreFetch}
              storeId={storeId}
              notify={notify}
              reload={() => {
                reload?.();
                setTick((t) => t + 1);
              }}
              onClose={() => setRenew(null)}
            />
          )}
        </>
      )}
    />
  );
}
