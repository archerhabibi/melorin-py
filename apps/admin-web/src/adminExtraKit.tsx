import { useEffect, useState } from 'react';
import { authFetch } from './api.ts';
import { Plus, Search, X } from 'lucide-react';
import { Badge, isStatus } from './ui.tsx';
import type { Json, Rec, Toast } from './types.ts';
// Shared primitives of the Coupons and Settings screens (moved verbatim out of AdminExtra.tsx).
export const money = (n: Json) => new Intl.NumberFormat('fa-IR').format(n || 0);
export const box = 'card';
export const inp = 'inp';
export const btn = 'btn';
export const ghost = 'btn btn-g';

export function useList(api: Json, path: string, toast: Toast) {
  const [rows, setRows] = useState<Rec[]>([]);
  const [tick, setTick] = useState(0);
  const call = (p: Json, o = {}) => authFetch(api.base, p, o);
  useEffect(() => {
    call(path)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => setRows(Array.isArray(d) ? d : d.items || []))
      .catch(() => toast('دریافت داده ناموفق بود'));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- T-W08: reviewed, dependency list intentionally limited (adding the flagged value risks refetch loops); verify in a browser before changing
  }, [path, tick]);
  return { rows, call, reload: () => setTick((x) => x + 1) };
}
export const Table = ({ cols, rows, title, extra }: { cols?: Json; rows?: Json; title?: Json; extra?: Json }) => {
  const [q, setQ] = useState('');
  const show = q
    ? rows.filter((r: Json) => r.some((c: Json) => typeof c === 'string' && c.toLowerCase().includes(q.toLowerCase())))
    : rows;
  return (
    <section className={`${box} rise overflow-hidden`}>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--ln)] px-5 py-4">
        <h3 className="font-extrabold">
          {title} <span className="text-xs font-medium text-[var(--mu)]">({show.length.toLocaleString('fa-IR')})</span>
        </h3>
        <div className="flex items-center gap-2">
          {extra}
          <label className="relative">
            <Search
              size={15}
              className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[var(--mu)]"
            />
            <input
              aria-label="جستجو"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="جستجو…"
              className={`${inp} w-44 pr-9`}
            />
          </label>
        </div>
      </div>
      <div className="max-h-[70vh] overflow-auto">
        <table className="tbl min-w-[640px]">
          <thead>
            <tr>
              {cols.map((c: Json, i: Json) => (
                <th key={i}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {show.length ? (
              show.map((r: Json, i: Json) => (
                <tr key={i}>
                  {r.map((c: Json, j: Json) => (
                    <td key={j}>{isStatus(c) ? <Badge s={c} /> : (c ?? '-')}</td>
                  ))}
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={cols.length} className="p-12 text-center text-[var(--mu)]">
                  {q ? 'نتیجه‌ای پیدا نشد' : 'داده‌ای وجود ندارد'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
};
export const JSONK = new Set(['cred', 'cfg']);
export const Form = ({ fields, onSubmit, label }: { fields?: Json; onSubmit?: Json; label?: Json }) => {
  const [v, setV] = useState<Rec>({});
  const [open, setOpen] = useState(false);
  if (!open)
    return (
      <div className="mb-5">
        <button className="btn" onClick={() => setOpen(true)}>
          <Plus size={16} />
          {label}
        </button>
      </div>
    );
  return (
    <section className="card rise mb-5 p-5">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="font-extrabold">{label}</h3>
        <button aria-label="بستن فرم" className="btn btn-g" onClick={() => setOpen(false)}>
          <X size={15} />
        </button>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {fields.map(([k, l, t]: Json) =>
          JSONK.has(k) ? (
            <label key={k} className="text-xs font-bold text-[var(--mu)] sm:col-span-2 lg:col-span-4">
              {l}
              <textarea
                rows={3}
                dir="ltr"
                spellCheck={false}
                className={`${inp} mt-1.5 font-mono text-xs`}
                value={v[k] ?? ''}
                onChange={(e) => setV({ ...v, [k]: e.target.value })}
              />
            </label>
          ) : (
            <label key={k} className="text-xs font-bold text-[var(--mu)]">
              {l}
              {t === 'select' ? (
                <select
                  dir="ltr"
                  className={`${inp} mt-1.5`}
                  value={v[k] ?? 'IRT'}
                  onChange={(e) => setV({ ...v, [k]: e.target.value })}
                >
                  <option value="IRT">IRT</option>
                  <option value="USD">USD</option>
                  <option value="USDT">USDT</option>
                  <option value="XTR">XTR</option>
                </select>
              ) : (
                <input
                  type={t || 'text'}
                  dir="ltr"
                  className={`${inp} mt-1.5`}
                  value={v[k] ?? ''}
                  onChange={(e) => setV({ ...v, [k]: e.target.value })}
                />
              )}
            </label>
          ),
        )}
      </div>
      <div className="mt-5 flex gap-2">
        <button
          className={btn}
          onClick={() =>
            onSubmit(v, () => {
              setV({});
              setOpen(false);
            })
          }
        >
          {label}
        </button>
        <button className="btn btn-g" onClick={() => setOpen(false)}>
          انصراف
        </button>
      </div>
    </section>
  );
};
