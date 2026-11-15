import type { ReactNode } from 'react';
// Admin → Reports & charts. One payload from GET /api/v1/admin/reports/analytics drives every card on the screen.
// Currency-safe (one currency at a time), compared with the previous period, exportable, with a table view for accessibility.
import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react';
import { API_BASE, authFetch } from '../../api/api.ts';
import { Sparkline } from './ReportCharts.tsx';
import { deltaInfo } from './reportsLogic.ts';
import type { Json, Rec } from '../../types.ts';

export const RANGES = [7, 30, 90];
export const METRICS = [
  ['revenue', 'فروش'],
  ['orders', 'سفارش'],
  ['cash_in', 'ورودی نقدی'],
  ['new_users', 'کاربر جدید'],
  ['cumulative', 'تجمعی'],
];
export const TONES: Rec = { ok: 'b-ok', wn: 'b-wn', in: 'b-in', bd: 'b-bd' };

export const Seg = ({ items, value, set, label }: { items?: Json; value?: Json; set?: Json; label?: Json }) => (
  <div role="tablist" aria-label={label} className="inline-flex rounded-lg bg-[var(--mb)] p-0.5">
    {items.map(([k, t]: Json) => (
      <button
        key={k}
        role="tab"
        aria-selected={value === k}
        onClick={() => set(k)}
        className={`rounded-md px-3 py-1 text-xs font-bold transition ${value === k ? 'bg-[var(--sf)] text-[var(--tx)] shadow-xs' : 'text-[var(--mu)]'}`}
      >
        {t}
      </button>
    ))}
  </div>
);

export function Delta({ delta, invert }: { delta?: Json; invert?: Json }) {
  const d = deltaInfo(delta, { invert });
  const Icon = d.dir === 'up' ? ArrowUpRight : d.dir === 'down' ? ArrowDownRight : Minus;
  const tone = d.good === null ? 'b-mu' : d.good ? 'b-ok' : 'b-bd';
  return (
    <span className={`badge ${tone} gap-1`} title="نسبت به بازه‌ی قبلیِ هم‌اندازه">
      <Icon size={12} aria-hidden="true" />
      {d.text}
    </span>
  );
}

export function Kpi({
  title,
  Icon,
  value,
  unit,
  kpi,
  color,
  invert,
  loading,
  hint,
}: {
  title?: Json;
  Icon?: Json;
  value?: Json;
  unit?: Json;
  kpi?: Json;
  color?: Json;
  invert?: Json;
  loading?: Json;
  hint?: Json;
}) {
  return (
    <div className="card rise p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="text-sm text-[var(--mu)]">{title}</div>
        <Icon size={16} className="text-[var(--mu)]" aria-hidden="true" />
      </div>
      {loading ? (
        <div className="skel mt-4 h-8 w-2/3" />
      ) : (
        <div className="mt-3 flex items-end justify-between gap-2">
          <div className="min-w-0">
            <div className="truncate text-2xl font-extrabold tracking-tight" title={`${value} ${unit || ''}`}>
              {value}
              {unit && <span className="mr-1 text-xs font-bold text-[var(--mu)]">{unit}</span>}
            </div>
            {hint && <div className="mt-1 text-[11px] text-[var(--mu)]">{hint}</div>}
          </div>
          <Sparkline values={kpi?.spark} color={color} />
        </div>
      )}
      <div className="mt-3 min-h-[22px]">{!loading && kpi && <Delta delta={kpi.delta_pct} invert={invert} />}</div>
    </div>
  );
}

export const Card = ({
  title,
  hint,
  right,
  children,
  className = '',
}: {
  title?: Json;
  hint?: Json;
  right?: Json;
  children?: ReactNode;
  className?: string;
}) => (
  <section className={`card rise p-5 ${className}`}>
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h3 className="font-extrabold">{title}</h3>
        {hint && <p className="mt-1 text-xs text-[var(--mu)]">{hint}</p>}
      </div>
      {right}
    </div>
    {children}
  </section>
);

export function DataTable({ cols, rows, caption }: { cols?: Json; rows?: Json; caption?: Json }) {
  return (
    <div className="max-h-[360px] overflow-auto rounded-xl border border-[var(--ln)]">
      <table className="tbl min-w-[520px]">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {cols.map((c: Json) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r: Json, i: Json) => (
            <tr key={i}>
              {r.map((c: Json, j: Json) => (
                <td key={j}>{c}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export async function download(path: string, filename: Json) {
  const r = await authFetch(API_BASE, path);
  if (!r.ok) throw new Error(`export ${r.status}`);
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export const EXPORTS = [
  ['daily', 'روزانه'],
  ['products', 'محصولات'],
  ['stores', 'فروشگاه‌ها'],
  ['methods', 'روش پرداخت'],
];
