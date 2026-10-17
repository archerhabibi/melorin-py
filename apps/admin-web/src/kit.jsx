// Shared building blocks for the catalog screens (VPN products, VPN sales bundles).
import { useCallback, useEffect, useRef, useState } from "react";
import { Check, LayoutGrid, List, Search, Trash2, X } from "lucide-react";
import { confirmDialog, noticeDialog } from "./ui.jsx";

export const num = (v) => Number(v || 0).toLocaleString("fa-IR");
export const tint = (t) => ({ background: `var(--${t}b, var(--mb))`, color: `var(--${t}, var(--mu))` });
/** Tone for a capacity ratio: red ≥100%, amber ≥80%, green otherwise. */
export const capTone = (u) => (u >= 1 ? "bd" : u >= 0.8 ? "wn" : "ok");

/** Chip list: first `max` items, then "+n" overflow badge. */
export function ChipList({ items = [], max = 3, renderItem }) {
  return <>{items.slice(0, max).map(renderItem)}{items.length > max && <span className="text-[11px] text-[var(--mu)]">+{num(items.length - max)}</span>}</>;
}

// Accept Persian / Arabic-Indic digits typed by the admin and normalise them to ASCII.
export const toEn = (s) => String(s ?? "").replace(/[۰-۹]/g, (d) => "۰۱۲۳۴۵۶۷۸۹".indexOf(d)).replace(/[٠-٩]/g, (d) => "٠١٢٣٤٥٦٧٨٩".indexOf(d));
export const digits = (s) => toEn(s).replace(/\D/g, "");

export async function errText(r, fallback) {
  try {
    const d = await r.json(); const det = d?.detail;
    return d?.error?.message || (typeof det === "string" ? det : det?.message) || (Array.isArray(det) && det[0]?.msg?.replace(/^Value error, /, "")) || fallback;
  } catch { return fallback; }
}

/** Red "delete" control used by cards, rows and drawer footers (same look everywhere). */
export function DeleteButton({ label = "حذف", compact = false, busy = false, onClick, className = "" }) {
  return <button type="button" className={`btn btn-g btn-d ${compact ? "!px-2" : ""} ${className}`} disabled={busy} aria-label={label} title={label} onClick={onClick}><Trash2 size={13} />{!compact && label}</button>;
}

/** Confirm → DELETE → report. The Core answers 409 with a plain reason when the item has history; that reason is shown in a dialog. Resolves true only when deleted. */
export async function removeEntity(call, path, { title, message, done, toast }) {
  if (!(await confirmDialog(message, { title, danger: true, ok: "حذف دائمی" }))) return false;
  try {
    const r = await call(path, { method: "DELETE" });
    if (!r.ok) {
      const why = await errText(r, "حذف ناموفق بود");
      if (r.status === 409) await noticeDialog(why, { title: "حذف ممکن نیست" }); else toast(why);
      return false;
    }
  } catch { toast("ارتباط با سرور برقرار نشد"); return false; }
  toast(done); return true;
}

export function useAlive() { const a = useRef(true); useEffect(() => () => { a.current = false; }, []); return a; }

/** Fetch a list endpoint once (and on reload). rows === null while loading. */
/** Fetch a list; pass `{ skip: true }` on screens that do not need this endpoint (lazy-loading #3). */
export function useRows(call, path, { skip = false } = {}) {
  const [rows, setRows] = useState(skip ? [] : null);
  const [failed, setFailed] = useState(false);
  const alive = useAlive();
  const load = useCallback(async () => {
    if (!path || skip) return;
    try {
      const r = await call(path);
      if (!r.ok) throw 0;
      const d = await r.json();
      if (alive.current) { setRows(Array.isArray(d) ? d : d.items || []); setFailed(false); }
    } catch {
      if (alive.current) { setFailed(true); setRows((x) => x || []); }
    }
  }, [path, skip]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!skip) load(); }, [load]); // eslint-disable-line react-hooks/exhaustive-deps
  return { rows: skip ? [] : rows, failed, load: skip ? () => Promise.resolve() : load };
}

/** Page navigation strip. Renders nothing when all items fit on one page. */
export function Paginator({ page, setPage, total, pageSize = 20 }) {
  const pages = Math.ceil(total / pageSize);
  if (pages <= 1) return null;
  return (
    <div className="flex items-center justify-center gap-3 pt-3">
      <button className="btn btn-g !py-1.5 !text-xs" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>«</button>
      <span className="text-xs text-[var(--mu)]">{num(page + 1)} / {num(pages)}</span>
      <button className="btn btn-g !py-1.5 !text-xs" disabled={page >= pages - 1} onClick={() => setPage((p) => p + 1)}>»</button>
    </div>
  );
}

export function Field({ label, hint, error, children }) {
  return <label className="block text-xs font-bold text-[var(--mu)]">{label}<div className="mt-1.5 font-normal">{children}</div>
    {(error || hint) && <span className={`mt-1 block text-[11px] font-normal leading-5 ${error ? "text-[var(--bd)]" : "text-[var(--mu)]"}`}>{error || hint}</span>}</label>;
}
export function Switch({ checked, onChange, disabled, label, title }) {
  return <button type="button" role="switch" aria-checked={checked} aria-label={label} title={title} disabled={disabled} onClick={() => onChange(!checked)} className="pv-sw disabled:opacity-50" data-on={checked}><span /></button>;
}
export function Toggle({ checked, onChange, label, hint }) {
  return <div className="flex items-start gap-3"><Switch checked={checked} onChange={onChange} label={label} /><span className="text-xs"><b>{label}</b>{hint && <span className="mt-0.5 block font-normal leading-5 text-[var(--mu)]">{hint}</span>}</span></div>;
}
export function Segmented({ value, onChange, options, label }) {
  return <div role="radiogroup" aria-label={label} className="pv-seg">{options.map(([v, l]) => <button key={v} type="button" role="radio" aria-checked={value === v} className={value === v ? "on" : ""} onClick={() => onChange(v)}>{l}</button>)}</div>;
}
/** One cell of a KpiBar. Clickable when `onClick` is given (acts as a filter toggle). */
export function Stat({ label, value, tone, active, onClick, Icon, sub, ring }) {
  const body = <>
    {ring != null
      ? <Ring value={ring} size={46} stroke={5} tone={tone} label={`${label}: ${Math.round(ring * 100)}٪`}><Icon size={16} style={{ color: `var(--${tone})` }} /></Ring>
      : <span className="tile h-11 w-11" style={tint(tone)}><Icon size={19} /></span>}
    <span className="min-w-0"><span className="num block text-2xl font-extrabold leading-none">{num(value)}</span><span className="mt-1.5 block truncate text-xs text-[var(--mu)]">{label}</span>{sub && <span className="mt-0.5 block truncate text-[11px] text-[var(--mu)]">{sub}</span>}</span>
  </>;
  return onClick ? <button type="button" onClick={onClick} aria-pressed={!!active} className="kpi">{body}</button> : <div className="kpi">{body}</div>;
}
/** Connected strip of Stat cells (replaces a loose grid of cards). */
export const KpiBar = ({ cols = 4, children }) => <div className="kpis rise" style={{ "--cols": cols }}>{children}</div>;

/** Section card. A title like "۲ · اتصال" renders the number as a step badge. */
export function Section({ title, hint, children }) {
  const m = /^([۰-۹0-9]+)\s·\s(.*)$/.exec(title || "");
  return <section className="card space-y-4 p-4 sm:p-5"><div><h3 className="flex items-center gap-2 text-[13px] font-extrabold">{m ? <><span className="sec-n">{m[1]}</span>{m[2]}</> : title}</h3>{hint && <p className="mt-1.5 text-[11px] leading-5 text-[var(--mu)]">{hint}</p>}</div>{children}</section>;
}

/* ---------- v2 visual primitives ---------- */
/** Circular gauge. value 0..1, tone = ok|wn|bd|in|mu. Children render in the centre. */
export function Ring({ value = 0, size = 56, stroke = 6, tone = "ok", label, children }) {
  const r = (size - stroke) / 2, c = 2 * Math.PI * r, v = Math.max(0, Math.min(1, value || 0));
  return <span className="gauge" style={{ width: size, height: size }} role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}><circle className="tr" cx={size / 2} cy={size / 2} r={r} strokeWidth={stroke} /><circle className="fg" cx={size / 2} cy={size / 2} r={r} strokeWidth={stroke} stroke={`var(--${tone})`} strokeDasharray={c} strokeDashoffset={c * (1 - v)} /></svg>
    <span className="relative grid place-items-center text-center leading-none">{children}</span>
  </span>;
}
/** Segmented capacity meter (value 0..1). */
export function SegMeter({ value = 0, tone = "ok", label, max, now }) {
  const v = Math.max(0, Math.min(1, value || 0));
  return <div className="seg" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={max} aria-valuenow={now}><i style={{ width: `${v * 100}%`, background: `var(--${tone})` }} /></div>;
}
/** Thin continuous bar. */
export const Bar = ({ value = 0, tone = "ok", label }) => <div className="bar" role="progressbar" aria-label={label} aria-valuenow={Math.round(value * 100)}><i style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%`, background: `var(--${tone})` }} /></div>;

/** Filter pills with live counts: options = [[key, label, count, { warn }]]. */
export function Pills({ value, onChange, options, label }) {
  return <div className="pills" role="group" aria-label={label}>{options.map(([k, l, n, o]) => <button key={k} type="button" aria-pressed={value === k} className={`pill ${o?.warn && n ? "warn" : ""}`} onClick={() => onChange(value === k && k !== "all" ? "all" : k)}>{l}<b className="num">{num(n)}</b></button>)}</div>;
}
export function SearchBox({ value, onChange, placeholder, label }) {
  return <label className="relative min-w-[12rem] flex-1 sm:max-w-sm"><Search size={15} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[var(--mu)]" /><input aria-label={label} className="inp !pr-9" placeholder={placeholder} value={value} onChange={(e) => onChange(e.target.value)} />{value && <button type="button" aria-label="پاک‌کردن جستجو" className="absolute left-2 top-1/2 -translate-y-1/2 rounded-md p-1 text-[var(--mu)] hover:bg-[var(--mb)]" onClick={() => onChange("")}><X size={13} /></button>}</label>;
}
export function SortSelect({ value, onChange, options }) {
  return <select aria-label="مرتب‌سازی" className="inp !w-auto !py-2 !text-xs font-bold" value={value} onChange={(e) => onChange(e.target.value)}>{options.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>;
}
export function ViewToggle({ value, onChange, options, disabled }) {
  const I = { grid: LayoutGrid, table: List, list: List, cards: LayoutGrid };
  return <div className="pv-seg" role="group" aria-label="نحوه نمایش">{options.map(([k, l]) => { const Ic = I[k] || LayoutGrid; return <button key={k} type="button" className={value === k ? "on" : ""} aria-pressed={value === k} title={l} aria-label={l} disabled={disabled} onClick={() => onChange(k)}><Ic size={14} /><span className="hidden sm:inline">{l}</span></button>; })}</div>;
}
export function Empty({ Icon, title, text, children }) {
  return <div className="empty rise"><span className="tile h-16 w-16 bg-[var(--mb)] text-[var(--mu)]"><Icon size={28} /></span><h3 className="text-lg font-extrabold">{title}</h3><p className="max-w-md text-sm leading-7 text-[var(--mu)]">{text}</p>{children}</div>;
}
export const ErrorBar = ({ children, onRetry }) => <p role="alert" className="flex items-center gap-2 rounded-xl bg-[var(--bdb)] p-3 text-sm text-[var(--bd)]">{children}{onRetry && <button className="font-extrabold underline" onClick={onRetry}>تلاش دوباره</button>}</p>;

/** Number input showing grouped digits; `value` is a string of ASCII digits. */
export function NumInput({ value, onChange, placeholder, suffix, ...rest }) {
  const shown = value === "" ? "" : Number(value).toLocaleString("en-US");
  return <div className="relative"><input {...rest} dir="ltr" inputMode="numeric" className={`inp ${suffix ? "!pr-14" : ""}`} value={shown} placeholder={placeholder} onChange={(e) => onChange(digits(e.target.value).replace(/^0+(?=\d)/, ""))} />
    {suffix && <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[11px] font-bold text-[var(--mu)]">{suffix}</span>}</div>;
}

/** Right-side drawer with dirty-guard on close, sticky footer and server-error slot. */
export function Drawer({ title, subtitle, icon, dirty, busy, onClose, children, footer, error, danger }) {
  const close = async () => { if (busy) return; if (dirty && !(await confirmDialog("تغییرات ذخیره‌نشده از بین می‌رود. بسته شود؟", { title: "بستن بدون ذخیره", danger: true, ok: "بستن" }))) return; onClose(); };
  return <div className="fixed inset-0 z-50" onKeyDown={(e) => e.key === "Escape" && close()}>
    <div className="pv-fade absolute inset-0 bg-black/55" onClick={close} />
    <aside role="dialog" aria-modal="true" aria-label={title} dir="rtl" className="pv-drawer absolute inset-y-0 right-0 flex w-full max-w-2xl flex-col border-l border-[var(--ln)] bg-[var(--bg)] shadow-2xl">
      <header className="flex items-center gap-3 border-b border-[var(--ln)] bg-[linear-gradient(180deg,var(--sf2),var(--sf))] px-5 py-4">
        {icon}
        <div className="min-w-0 flex-1"><h2 className="truncate text-lg font-extrabold">{title}</h2>{subtitle && <p className="mt-0.5 truncate text-xs text-[var(--mu)]">{subtitle}</p>}</div>
        {dirty && <span className="badge b-wn">تغییرات ذخیره‌نشده</span>}
        <button className="btn btn-g !px-2" aria-label="بستن" onClick={close} disabled={busy}><X size={16} /></button>
      </header>
      <div className="flex-1 space-y-4 overflow-y-auto bg-[var(--bg)] p-4 sm:p-5">{children}</div>
      <footer className="border-t border-[var(--ln)] bg-[var(--sf)] px-5 py-3">
        {error && <p role="alert" className="mb-3 rounded-lg bg-[var(--bdb)] p-3 text-xs leading-6 text-[var(--bd)]">{error}</p>}
        <div className="flex flex-wrap items-center gap-2">{footer}<button className="btn btn-g !py-2 !text-sm" onClick={close} disabled={busy}>انصراف</button>{danger && <span className="mr-auto">{danger}</span>}</div>
      </footer>
    </aside>
  </div>;
}
export const Saved = ({ on }) => on ? <span className="inline-flex items-center gap-1 text-xs font-bold text-[var(--ok)]"><Check size={14} />ذخیره شد</span> : null;
