import { useEffect, useRef, useState } from 'react';
import { RefreshCw, X } from 'lucide-react';
import { Loading, StatusBadge, fa } from '../ui.tsx';
import AccountInquiry from '../AccountInquiry.tsx';
import { errOf } from './ResellerSettings.tsx';
import type { Json } from '../types';

export const J = { 'Content-Type': 'application/json' };

// The reseller renews his own accounts and HIS OWN store's customers' accounts. Core decides everything (window, package,
// price, wallet); this card shows Core's answer and asks Core to renew. The charge goes to the account holder's wallet.
function OwnerRenew({
  account,
  base,
  coreFetch,
  notify,
  onDone,
  onClose,
}: {
  account?: Json;
  base?: Json;
  coreFetch?: Json;
  notify?: Json;
  onDone?: Json;
  onClose?: Json;
}) {
  const [info, setInfo] = useState<Json>(null);
  const [busy, setBusy] = useState(false);
  const key = useRef(`web-owner-renew-${crypto.randomUUID()}`);
  useEffect(() => {
    let live = true;
    coreFetch(`${base}/accounts/${account.id}/renewal`)
      .then((r: Json) => (r.ok ? r.json() : Promise.reject()))
      .then((d: Json) => live && setInfo(d))
      .catch(() => live && setInfo({ renewable: false, message: 'اطلاعات تمدید دریافت نشد.' }));
    return () => {
      live = false;
    };
  }, [account.id, base, coreFetch]);
  async function go() {
    setBusy(true);
    try {
      const r = await coreFetch(`${base}/accounts/${account.id}/renew`, {
        method: 'POST',
        headers: { ...J, 'Idempotency-Key': key.current },
        body: JSON.stringify({ channel: 'web' }),
      });
      if (!r.ok) return notify(await errOf(r, 'تمدید ناموفق بود'));
      notify('تمدید ثبت شد');
      onDone();
      onClose();
    } finally {
      setBusy(false);
    }
  }
  const after = info?.after;
  return (
    <div className="mt-4 rounded-xl bg-surface2 p-3 text-sm">
      <div className="flex items-center justify-between">
        <b>تمدید اکانت{account.is_own ? '' : ' مشتری'}</b>
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
              {after.traffic_gb ? `${fa(after.traffic_gb)} گیگ` : 'نامحدود'}؛ روزهای باقی‌مانده فعلی جایگزین می‌شود،
              اضافه نمی‌شود.
            </div>
          )}
          <div className="mt-3 flex items-center justify-between gap-3 border-t border-line pt-3">
            <span>
              مبلغ:{' '}
              <b>
                {fa(info.package.price)} {info.package.currency}
              </b>
              {info.payer_note && <span className="block text-xs text-muted">{info.payer_note}</span>}
            </span>
            <button disabled={busy} onClick={go} className="btn-primary !px-4 !py-2 text-xs">
              تمدید
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function OwnerAccounts({ coreFetch, base, notify }: { coreFetch?: Json; base?: Json; notify?: Json }) {
  const [renew, setRenew] = useState<Json>(null);
  const [tick, setTick] = useState(0);
  return (
    <AccountInquiry
      coreFetch={coreFetch}
      base={`${base}/accounts`}
      owner
      notify={notify}
      reloadKey={tick}
      emptyText="هنوز اکانتی نساخته‌اید. اکانت مشتریان را با جستجو پیدا کنید."
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
          {renew === a.id && (
            <OwnerRenew
              account={a}
              base={base}
              coreFetch={coreFetch}
              notify={notify}
              onDone={() => setTick((t) => t + 1)}
              onClose={() => setRenew(null)}
            />
          )}
        </>
      )}
    />
  );
}
export const card = 'card';
export const btn = 'btn-primary !py-2.5';
export const ghost = 'btn-ghost';
export const inp = 'input !py-2.5';
export const SCOPES = [
  'catalog:read',
  'customers:read',
  'customers:wallet:write',
  'orders:read',
  'wallet:read',
  'reports:read',
];
export const EVENTS = [
  'order.completed',
  'order.refunded',
  'order.provisioning_failed',
  'payment.succeeded',
  'payment.failed',
  'wallet.changed',
  'vpn_account.expired',
  'vpn_account.near_expiry',
  'reseller.debt',
];

export function useGet(coreFetch: Json, path: Json, deps = []) {
  const [d, setD] = useState<Json>(null);
  const [t, setT] = useState(0);
  useEffect(() => {
    if (!path) return;
    coreFetch(path)
      .then((r: Json) => (r.ok ? r.json() : Promise.reject()))
      .then(setD)
      .catch(() => setD([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- T-W08: reviewed, dependency list intentionally limited (adding the flagged value risks refetch loops); verify in a browser before changing
  }, [path, t, coreFetch, ...deps]);
  return [d, () => setT((x) => x + 1)];
}

export function Overview({ coreFetch, base }: { coreFetch?: Json; base?: Json }) {
  const [p] = useGet(coreFetch, `${base}/profile`);
  const [rep] = useGet(coreFetch, `${base}/reports`);
  const w = p?.main_wallet;
  return (
    <div className="grid gap-4 md:grid-cols-3">
      <div className="rounded-2xl bg-hero p-5 text-white">
        <div className="text-sm text-white/60">اعتبار کیف پول اصلی</div>
        <div className="mt-2 text-2xl font-extrabold" dir="ltr">
          {fa(w?.balance)} {w?.currency}
        </div>
        <div className="mt-2 text-xs text-accent">وضعیت بدهی: {w?.debt_state || '—'}</div>
      </div>
      <div className={card}>
        <div className="text-sm text-muted">سقف بدهی</div>
        <div className="mt-2 text-2xl font-extrabold">{fa(p?.debt_limit)}</div>
        <div className="mt-2 text-xs">
          فروش: {p?.sales_enabled ? 'فعال' : 'غیرفعال'} · API: {p?.api_enabled ? 'فعال' : 'غیرفعال'}
        </div>
      </div>
      <div className={card}>
        <div className="text-sm text-muted">فروشگاه</div>
        <div className="mt-2 text-xl font-extrabold">{p?.store_name || '—'}</div>
        <div className="mt-2 text-xs">ارز: {p?.store_currency}</div>
      </div>
      <div className={`${card} md:col-span-3`}>
        <h4 className="font-extrabold">گزارش سفارش‌ها</h4>
        <table className="mt-3 w-full text-right text-sm">
          <thead className="text-xs text-muted [&_th]:pb-3 [&_th]:font-bold">
            <tr>
              <th>وضعیت</th>
              <th>تعداد</th>
              <th>فروش</th>
              <th>بهای تمام‌شده</th>
            </tr>
          </thead>
          <tbody>
            {(rep?.orders || []).map((o: Json) => (
              <tr key={o.status} className="border-t border-line">
                <td className="py-2.5">
                  <StatusBadge status={o.status} />
                </td>
                <td>{fa(o.count)}</td>
                <td>{fa(o.total)}</td>
                <td>{fa(o.reseller_cost)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function Customers({ coreFetch, base, notify }: { coreFetch?: Json; base?: Json; notify?: Json }) {
  const [rows, reload] = useGet(coreFetch, `${base}/customers`);
  const adjust = async (c: Json) => {
    const amount = Number(window.prompt('مبلغ (مثبت = شارژ، منفی = اصلاح):', ''));
    if (!amount) return;
    const reason = window.prompt('دلیل:', '');
    if (!reason || reason.length < 3) return;
    const r = await coreFetch(`${base}/customers/${c.user_id}/wallet`, {
      method: 'POST',
      headers: J,
      body: JSON.stringify({ amount, reason, idempotency_key: `rs-${crypto.randomUUID()}` }),
    });
    notify(r.ok ? 'کیف پول مشتری به‌روز شد' : 'عملیات ناموفق بود');
    r.ok && reload();
  };
  return (
    <div className={`${card} overflow-x-auto`}>
      <table className="w-full min-w-[620px] text-right text-sm">
        <thead className="text-xs text-muted [&_th]:pb-3 [&_th]:font-bold">
          <tr>
            <th>نام</th>
            <th>ایمیل</th>
            <th>آیدی تلگرام</th>
            <th>وضعیت</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {(rows || []).map((c: Json) => (
            <tr key={c.user_id} className="border-t border-line">
              <td className="py-3">{c.display_name || '-'}</td>
              <td className="latin">{c.email || '-'}</td>
              <td className="latin">{c.telegram_id || '-'}</td>
              <td>
                <StatusBadge status={c.status} />
              </td>
              <td>
                <button className={ghost} onClick={() => adjust(c)}>
                  شارژ/اصلاح کیف پول
                </button>
              </td>
            </tr>
          ))}
          {rows && !rows.length && (
            <tr>
              <td colSpan={5} className="p-8 text-center text-muted">
                مشتری‌ای وجود ندارد
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

export function Payments({ coreFetch, base, notify }: { coreFetch?: Json; base?: Json; notify?: Json }) {
  const [rows, reload] = useGet(coreFetch, `${base}/payments`);
  const review = async (p: Json, approve: Json) => {
    const note = approve ? null : window.prompt('دلیل رد:', '');
    if (!approve && note === null) return;
    const r = await coreFetch(`${base}/payments/${p.id}/review`, {
      method: 'POST',
      headers: J,
      body: JSON.stringify({ approve, note }),
    });
    notify(r.ok ? 'ثبت شد' : 'بررسی ناموفق بود');
    r.ok && reload();
  };
  return (
    <div className={`${card} overflow-x-auto`}>
      <table className="w-full min-w-[520px] text-right text-sm">
        <thead className="text-xs text-muted [&_th]:pb-3 [&_th]:font-bold">
          <tr>
            <th>مبلغ</th>
            <th>درگاه</th>
            <th>وضعیت</th>
            <th>رسید</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {(rows || []).map((p: Json) => (
            <tr key={p.id} className="border-t border-line">
              <td className="py-3">
                {fa(p.amount)} {p.currency}
              </td>
              <td>{p.provider}</td>
              <td>
                <StatusBadge status={p.status} />
              </td>
              <td>{p.has_receipt ? 'دارد' : 'ندارد'}</td>
              <td>
                {p.status !== 'succeeded' && p.status !== 'failed' && p.has_receipt ? (
                  <span className="flex gap-1.5">
                    <button className={ghost} onClick={() => review(p, true)}>
                      تأیید
                    </button>
                    <button className={ghost} onClick={() => review(p, false)}>
                      رد
                    </button>
                  </span>
                ) : (
                  ''
                )}
              </td>
            </tr>
          ))}
          {rows && !rows.length && (
            <tr>
              <td colSpan={5} className="p-8 text-center text-muted">
                پرداختی وجود ندارد
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
