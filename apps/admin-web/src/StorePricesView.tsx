// «قیمت‌ها» tab of the store hub: READ-ONLY view of the retail prices a reseller store charges, per product and sales bundle.
// Only the reseller sets these (reseller panel / bot); the admin sees them next to the cost floor so a below-cost or unpriced
// package is spotted without opening the reseller's panel. Source: GET /admin/stores/{id}/reseller-prices.
import { useCallback, useEffect, useState } from 'react';
import { authFetch } from './api.ts';
import { Empty, ErrorBar, num, useRows } from './kit.tsx';
import type { Json, Rec, Toast } from './types.ts';

const STATE: Rec = {
  ok: ['b-ok', 'قابل فروش'],
  unset: ['b-mu', 'بدون قیمت'],
  below_cost: ['b-bd', 'زیر قیمت همکاری'],
};
const StateBadge = ({ s }: { s?: Json }) => {
  const [cls, text] = STATE[s] || ['b-mu', String(s || '—')];
  return <span className={`badge ${cls}`}>{text}</span>;
};
const unit = (c: Json) => ({ IRT: 'تومان', IRR: 'ریال' })[c as 'IRT' | 'IRR'] || c || '';
const price = (v: Json, c: Json) => (v ? `${num(v)} ${unit(c)}` : '—');

export default function StorePricesView({ api, toast }: { api?: Json; toast: Toast }) {
  const call = useCallback((p: string, o?: RequestInit) => authFetch(api.base, p, o), [api.base]);
  const { rows: stores, failed } = useRows(call, '/api/v1/admin/resellers');
  const [storeId, setStoreId] = useState('');
  const [table, setTable] = useState<Rec[] | null>(null);

  useEffect(() => {
    setTable(null);
    if (!storeId) return;
    let live = true;
    (async () => {
      try {
        const r = await call(`/api/v1/admin/stores/${storeId}/reseller-prices`);
        if (!r.ok) throw new Error(String(r.status));
        const d = await r.json();
        if (live) setTable(d);
      } catch {
        if (live) toast('دریافت قیمت‌های فروشگاه ناموفق بود');
      }
    })();
    return () => {
      live = false;
    };
  }, [call, storeId, toast]);

  return (
    <section className="card space-y-3 p-4">
      <p className="text-sm">
        قیمت فروش را فقط خود نماینده تعیین می‌کند؛ اینجا فقط‌خواندنی است و کنار قیمت همکاری (کف قیمت) نمایش داده می‌شود.
      </p>
      {failed && <ErrorBar>دریافت فهرست نمایندگان ناموفق بود.</ErrorBar>}
      <select className="inp" value={storeId} onChange={(e) => setStoreId(e.target.value)} aria-label="فروشگاه نماینده">
        <option value="">یک فروشگاه نماینده انتخاب کنید</option>
        {(stores || []).map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </select>
      {storeId && table === null && <div className="skel h-24" />}
      {table && table.length === 0 && <Empty>برای این فروشگاه محصولی فعال نشده است.</Empty>}
      {table && table.length > 0 && (
        <div className="overflow-x-auto">
          <table className="tbl min-w-[720px]">
            <thead>
              <tr>
                <th>محصول / بسته فروش</th>
                <th>قیمت همکاری</th>
                <th>قیمت فروش</th>
                <th>وضعیت</th>
              </tr>
            </thead>
            <tbody>
              {table.map((p) => (
                <FragmentRows key={p.product_id} p={p} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function FragmentRows({ p }: { p: Rec }) {
  return (
    <>
      <tr className="font-extrabold">
        <td>{p.name}</td>
        <td>از {price(p.cost_floor, p.currency)}</td>
        <td>{price(p.customer_price, p.currency)}</td>
        <td>
          <StateBadge s={p.state} />
        </td>
      </tr>
      {(p.bundles || []).map((b: Rec) => (
        <tr key={b.bundle_id} className="text-[var(--mu)]">
          <td className="pr-6">{b.bundle_name}</td>
          <td>{price(b.cost, p.currency)}</td>
          <td>{price(b.effective_price, p.currency)}</td>
          <td>
            <StateBadge s={b.state} />
          </td>
        </tr>
      ))}
    </>
  );
}
