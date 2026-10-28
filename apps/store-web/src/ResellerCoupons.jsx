// Reseller panel › Discount codes. A code made here works ONLY in this reseller's store, in this store's currency, on products
// this store sells, and the reseller pays for the discount himself. Core enforces all of it; the screen only shows the result.
import { useCallback, useEffect, useState } from 'react';
import { Percent, Plus } from 'lucide-react';
import { Empty, Loading, fa } from './ui.jsx';
import { percentToBp, toInt, unitOf } from './storeProgram.js';

const J = { 'Content-Type': 'application/json' };
const STATUS = { active: 'فعال', disabled: 'غیرفعال', archived: 'بایگانی' };

export default function ResellerCoupons({ coreFetch, storeId, notify, currency }) {
  const [rows, setRows] = useState(null);
  const [failed, setFailed] = useState(false);
  const [f, setF] = useState({ code: '', pct: '', fixed: '', cap: '', total: '', each: '1' });
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try {
      const r = await coreFetch(`/api/v1/stores/${storeId}/coupons`);
      if (!r.ok) throw new Error('load');
      setRows(await r.json());
    } catch {
      setFailed(true);
    }
  }, [coreFetch, storeId]);
  useEffect(() => {
    load();
  }, [load]);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const pctBp = f.pct ? percentToBp(f.pct) : 0;
  const fixed = f.fixed ? toInt(f.fixed) : 0;
  const invalid =
    !/^[A-Za-z0-9_-]{3,50}$/.test(f.code) || pctBp == null || fixed == null || (!pctBp && !fixed) || pctBp > 10000;
  async function create(e) {
    e.preventDefault();
    if (invalid) return;
    setBusy(true);
    const r = await coreFetch(`/api/v1/stores/${storeId}/coupons`, {
      method: 'POST',
      headers: J,
      body: JSON.stringify({
        code: f.code,
        percent_bp: pctBp,
        fixed,
        max_discount: f.cap ? toInt(f.cap) : null,
        max_redemptions: f.total ? toInt(f.total) : null,
        per_customer_limit: toInt(f.each) || 1,
      }),
    });
    setBusy(false);
    if (r.ok) {
      notify('کد تخفیف ساخته شد');
      setF({ code: '', pct: '', fixed: '', cap: '', total: '', each: '1' });
      load();
    } else {
      const d = await r.json().catch(() => ({}));
      notify(d?.error?.message || 'ساخت کد ناموفق بود');
    }
  }
  async function toggle(c) {
    const r = await coreFetch(`/api/v1/stores/${storeId}/coupons/${c.id}`, {
      method: 'PATCH',
      headers: J,
      body: JSON.stringify({ status: c.status === 'active' ? 'disabled' : 'active' }),
    });
    r.ok ? load() : notify('تغییر ناموفق بود');
  }
  if (failed) return <Empty text="کدهای تخفیف در دسترس نیست." />;
  if (!rows) return <Loading rows={3} />;
  return (
    <div className="space-y-4">
      <form onSubmit={create} className="card space-y-3" aria-label="ساخت کد تخفیف">
        <h4 className="flex items-center gap-2 font-extrabold">
          <Percent size={18} aria-hidden="true" /> کد تخفیف جدید برای فروشگاه من
        </h4>
        <div className="grid gap-3 sm:grid-cols-3">
          <label className="text-sm">
            کد
            <input className="input latin mt-1" dir="ltr" value={f.code} onChange={set('code')} />
          </label>
          <label className="text-sm">
            درصد تخفیف
            <input className="input latin mt-1" dir="ltr" inputMode="decimal" value={f.pct} onChange={set('pct')} />
          </label>
          <label className="text-sm">
            {`تخفیف ثابت (${unitOf(currency)})`}
            <input className="input latin mt-1" dir="ltr" inputMode="numeric" value={f.fixed} onChange={set('fixed')} />
          </label>
          <label className="text-sm">
            سقف تخفیف
            <input className="input latin mt-1" dir="ltr" inputMode="numeric" value={f.cap} onChange={set('cap')} />
          </label>
          <label className="text-sm">
            سقف کل استفاده
            <input className="input latin mt-1" dir="ltr" inputMode="numeric" value={f.total} onChange={set('total')} />
          </label>
          <label className="text-sm">
            سقف هر مشتری
            <input className="input latin mt-1" dir="ltr" inputMode="numeric" value={f.each} onChange={set('each')} />
          </label>
        </div>
        <button className="btn-primary" disabled={busy || invalid}>
          <Plus size={15} aria-hidden="true" /> ساخت کد
        </button>
      </form>
      {rows.length === 0 ? (
        <Empty text="هنوز کد تخفیفی نساخته‌اید." />
      ) : (
        <div className="card overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead className="text-muted">
              <tr>
                {['کد', 'تخفیف', 'استفاده', 'وضعیت', ''].map((h) => (
                  <th key={h} className="px-4 py-3 text-right font-bold">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id} className="border-t border-[var(--ln)]">
                  <td className="latin px-4 py-3 font-bold">{c.code}</td>
                  <td className="px-4 py-3">
                    {[
                      c.percent_bp ? `${fa(c.percent_bp / 100)}٪` : null,
                      c.fixed ? `${fa(c.fixed)} ${unitOf(c.currency)}` : null,
                    ]
                      .filter(Boolean)
                      .join(' + ')}
                  </td>
                  <td className="px-4 py-3">{`${fa(c.redemptions ?? 0)}/${c.max_redemptions ? fa(c.max_redemptions) : '∞'}`}</td>
                  <td className="px-4 py-3">{STATUS[c.status] || c.status}</td>
                  <td className="px-4 py-3">
                    <button className="btn-soft" onClick={() => toggle(c)}>
                      {c.status === 'active' ? 'غیرفعال' : 'فعال'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
