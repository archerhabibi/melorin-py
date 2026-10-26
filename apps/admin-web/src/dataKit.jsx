// Shared building blocks for the data screens (orders, VPN accounts, users, stores, audit).
// Keeps the five screens visually and behaviourally identical: header → KPI filters → toolbar →
// table → detail drawer, with the same loading / empty / error / pagination states.
import { useEffect, useMemo, useState } from 'react';
import { Check, ChevronLeft, Copy, Download, RefreshCw } from 'lucide-react';
import { authFetch } from './api.js';
import { num } from './kit.jsx';

export const PAGE_SIZE = 20;

/** Stable authFetch bound to the API base. */
export const useCall = (api) => useMemo(() => (p, o = {}) => authFetch(api.base, p, o), [api.base]);

/** Debounced copy of a fast-changing value (search boxes). */
export function useDebounced(value, ms = 300) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** id → record lookup for resolving store / user names inside other lists. */
export const indexBy = (rows, key = 'id') => Object.fromEntries((rows || []).map((r) => [r[key], r]));

const CUR = { IRT: 'تومان', IRR: 'ریال', USD: 'دلار', USDT: 'تتر' };
export const curLabel = (c) => CUR[c] || c || '';
export const money = (v, c) => `${num(v)}${c ? ` ${curLabel(c)}` : ''}`;

const UNITS = ['بایت', 'کیلوبایت', 'مگابایت', 'گیگابایت', 'ترابایت'];
export function fmtBytes(n) {
  let v = Number(n || 0);
  let i = 0;
  while (v >= 1024 && i < UNITS.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toLocaleString('fa-IR', { maximumFractionDigits: v >= 100 || i === 0 ? 0 : 1 })} ${UNITS[i]}`;
}

const RTF = typeof Intl !== 'undefined' ? new Intl.RelativeTimeFormat('fa', { numeric: 'auto' }) : null;
/** "۳ ساعت پیش" / "فردا" for a date-ish value; '' when unparsable. */
export function relTime(v, now = Date.now()) {
  const t = v ? new Date(v).getTime() : NaN;
  if (!RTF || Number.isNaN(t)) return '';
  const s = Math.round((t - now) / 1000);
  const steps = [
    [60, 'second'],
    [3600, 'minute'],
    [86400, 'hour'],
    [2592000, 'day'],
    [31536000, 'month'],
    [Infinity, 'year'],
  ];
  const div = { second: 1, minute: 60, hour: 3600, day: 86400, month: 2592000, year: 31536000 };
  for (const [lim, unit] of steps) {
    if (Math.abs(s) < lim) return RTF.format(Math.round(s / div[unit]), unit);
  }
  return '';
}

/** Date + relative age, stacked, for table cells. */
export function When({ v }) {
  if (!v) return <span className="text-[var(--mu)]">—</span>;
  const d = new Date(v);
  return (
    <span className="block leading-5">
      <span className="num block text-[13px]">
        {d.toLocaleDateString('fa-IR', { dateStyle: 'medium' })}{' '}
        <span className="text-[var(--mu)]">{d.toLocaleTimeString('fa-IR', { timeStyle: 'short' })}</span>
      </span>
      <span className="block text-[11px] text-[var(--mu)]">{relTime(v)}</span>
    </span>
  );
}

/** Neutralise spreadsheet formula prefixes (=, +, -, @, tab, CR) and quote the cell. */
export const csvCell = (v) => {
  let s = v == null ? '' : String(v);
  if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return `"${s.replace(/"/g, '""')}"`;
};
export function downloadCsv(name, head, rows) {
  const csv = [head.map(csvCell).join(','), ...rows.map((r) => r.map(csvCell).join(','))].join('\r\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' }));
  a.download = `${name}-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

/** Screen title + subtitle + actions (refresh, CSV, …). */
export function ScreenHead({ title, hint, count, onRefresh, busy, onExport, exportDisabled, children }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h2 className="flex items-center gap-2 text-xl font-extrabold">
          {title}
          {count != null && <span className="badge b-mu num">{num(count)}</span>}
        </h2>
        {hint && <p className="mt-1 text-xs leading-6 text-[var(--mu)]">{hint}</p>}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {children}
        {onExport && (
          <button className="btn btn-g !py-2" disabled={exportDisabled} onClick={onExport}>
            <Download size={15} />
            خروجی CSV
          </button>
        )}
        {onRefresh && (
          <button className="btn btn-g !px-3 !py-2" aria-label="به‌روزرسانی" title="به‌روزرسانی" onClick={onRefresh} disabled={busy}>
            <RefreshCw size={15} className={busy ? 'animate-spin' : ''} />
          </button>
        )}
      </div>
    </div>
  );
}

/** Sticky toolbar wrapper shared by every screen. */
export const Toolbar = ({ children }) => <div className="tool rise">{children}</div>;

/**
 * Responsive table. columns: [{ key, label, render(row), className }]; rows are plain objects.
 * Rows are keyboard-activatable when onRowClick is set; skeleton rows while `loading`.
 */
export function DataGrid({ columns, rows, rowKey = 'id', onRowClick, loading, emptyNode, caption, minWidth = 760 }) {
  const open = (r) => onRowClick && onRowClick(r);
  return (
    <section className="card rise overflow-hidden">
      <div className="max-h-[68vh] overflow-auto">
        <table className="tbl" style={{ minWidth }}>
          {caption && <caption className="sr-only">{caption}</caption>}
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c.key} scope="col" className={c.className}>
                  {c.label}
                </th>
              ))}
              {onRowClick && <th scope="col" className="w-10" aria-label="جزئیات" />}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              Array.from({ length: 6 }, (_, i) => (
                <tr key={i}>
                  <td colSpan={columns.length + (onRowClick ? 1 : 0)}>
                    <div className="skel h-5 w-full" />
                  </td>
                </tr>
              ))
            ) : rows.length ? (
              rows.map((r) => (
                <tr
                  key={r[rowKey]}
                  className={onRowClick ? 'cursor-pointer' : ''}
                  tabIndex={onRowClick ? 0 : undefined}
                  onClick={() => open(r)}
                  onKeyDown={(e) => {
                    if (onRowClick && (e.key === 'Enter' || e.key === ' ') && e.target === e.currentTarget) {
                      e.preventDefault();
                      open(r);
                    }
                  }}
                >
                  {columns.map((c) => (
                    <td key={c.key} className={c.className}>
                      {c.render(r)}
                    </td>
                  ))}
                  {onRowClick && (
                    <td className="text-[var(--mu)]">
                      <ChevronLeft size={16} aria-hidden="true" />
                    </td>
                  )}
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={columns.length + (onRowClick ? 1 : 0)} className="p-0">
                  {emptyNode}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** Circular initial badge used for people and stores. */
export function Avatar({ name, tone = 'in', size = 36 }) {
  const ch = String(name || '?').trim().charAt(0).toUpperCase() || '?';
  return (
    <span
      aria-hidden="true"
      className="tile font-extrabold"
      style={{ width: size, height: size, borderRadius: 999, fontSize: size * 0.4, background: `var(--${tone}b)`, color: `var(--${tone})` }}
    >
      {ch}
    </span>
  );
}

/** Two-line cell: main text + muted sub text (truncates, never wraps the row). */
export function Cell2({ main, sub, dir, mono }) {
  return (
    <span className="block min-w-0 leading-5">
      <span className={`block truncate font-bold ${mono ? 'num' : ''}`} dir={dir} title={typeof main === 'string' ? main : undefined}>
        {main || '—'}
      </span>
      {sub ? (
        <span className="block truncate text-[11px] text-[var(--mu)]" dir={dir} title={typeof sub === 'string' ? sub : undefined}>
          {sub}
        </span>
      ) : null}
    </span>
  );
}

/** Label / value list for drawers; `copy` adds a copy button, `ltr` forces direction for ids and urls. */
export function Facts({ items }) {
  return (
    <dl className="divide-y divide-[var(--ln)] overflow-hidden rounded-xl border border-[var(--ln)] bg-[var(--sf)]">
      {items
        .filter((x) => x && x.value != null && x.value !== '')
        .map((x) => (
          <div key={x.label} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
            <dt className="shrink-0 text-xs text-[var(--mu)]">{x.label}</dt>
            <dd className="flex min-w-0 items-center gap-1.5 font-bold">
              <span className="min-w-0 break-all" dir={x.ltr ? 'ltr' : undefined}>
                {x.value}
              </span>
              {x.copy && <MiniCopy text={x.copy === true ? String(x.value) : x.copy} />}
            </dd>
          </div>
        ))}
    </dl>
  );
}

function MiniCopy({ text }) {
  const [ok, setOk] = useState(false);
  return (
    <button
      type="button"
      className="rounded-md p-1 text-[var(--mu)] hover:bg-[var(--mb)]"
      aria-label="کپی"
      title="کپی"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setOk(true);
          setTimeout(() => setOk(false), 1200);
        } catch {
          /* clipboard unavailable */
        }
      }}
    >
      {ok ? <Check size={13} /> : <Copy size={13} />}
    </button>
  );
}

/** Slice a filtered list into a page. */
export const pageOf = (rows, page, size = PAGE_SIZE) => rows.slice(page * size, page * size + size);

/** Case-insensitive, Persian-digit-tolerant substring match over several fields. */
export const norm = (s) =>
  String(s ?? '')
    .toLowerCase()
    .replace(/[۰-۹]/g, (d) => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d))
    .replace(/[٠-٩]/g, (d) => '٠١٢٣٤٥٦٧٨٩'.indexOf(d));
export const matches = (q, ...fields) => {
  const n = norm(q).trim();
  return !n || fields.some((f) => norm(f).includes(n));
};
