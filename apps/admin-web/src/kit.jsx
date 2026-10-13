// Shared building blocks for the catalog screens (VPN products, VPN panel groups).
import { useCallback, useEffect, useRef, useState } from "react";
import { Check, X } from "lucide-react";
import { confirmDialog } from "./ui.jsx";

export const num = (n) => Number(n || 0).toLocaleString("fa-IR");
export const tint = (t) => ({ background: `var(--${t}b, var(--mb))`, color: `var(--${t}, var(--mu))` });
// Accept Persian / Arabic-Indic digits typed by the admin and normalise them to ASCII.
export const toEn = (s) => String(s ?? "").replace(/[۰-۹]/g, (d) => "۰۱۲۳۴۵۶۷۸۹".indexOf(d)).replace(/[٠-٩]/g, (d) => "٠١٢٣٤٥٦٧٨٩".indexOf(d));
export const digits = (s) => toEn(s).replace(/\D/g, "");

export async function errText(r, fallback) {
  try {
    const d = await r.json(); const det = d?.detail;
    return d?.error?.message || (typeof det === "string" ? det : det?.message) || (Array.isArray(det) && det[0]?.msg?.replace(/^Value error, /, "")) || fallback;
  } catch { return fallback; }
}

export function useAlive() { const a = useRef(true); useEffect(() => () => { a.current = false; }, []); return a; }

/** Fetch a list endpoint once (and on reload). rows === null while loading. */
export function useRows(call, path) {
  const [rows, setRows] = useState(null); const [failed, setFailed] = useState(false); const alive = useAlive();
  const load = useCallback(async () => {
    try { const r = await call(path); if (!r.ok) throw 0; const d = await r.json(); if (alive.current) { setRows(Array.isArray(d) ? d : d.items || []); setFailed(false); } }
    catch { if (alive.current) { setFailed(true); setRows((x) => x || []); } }
  }, [path]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);
  return { rows, failed, load };
}

export function Field({ label, hint, error, children }) {
  return <label className="block text-xs font-bold text-[var(--mu)]">{label}<div className="mt-1.5 font-normal">{children}</div>
    {(error || hint) && <span className={`mt-1 block text-[11px] font-normal leading-5 ${error ? "text-[var(--bd)]" : "text-[var(--mu)]"}`}>{error || hint}</span>}</label>;
}
export function Switch({ checked, onChange, disabled, label }) {
  return <button type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled} onClick={() => onChange(!checked)} className="pv-sw disabled:opacity-50" data-on={checked}><span /></button>;
}
export function Toggle({ checked, onChange, label, hint }) {
  return <div className="flex items-start gap-3"><Switch checked={checked} onChange={onChange} label={label} /><span className="text-xs"><b>{label}</b>{hint && <span className="mt-0.5 block font-normal leading-5 text-[var(--mu)]">{hint}</span>}</span></div>;
}
export function Segmented({ value, onChange, options, label }) {
  return <div role="radiogroup" aria-label={label} className="pv-seg">{options.map(([v, l]) => <button key={v} type="button" role="radio" aria-checked={value === v} className={value === v ? "on" : ""} onClick={() => onChange(v)}>{l}</button>)}</div>;
}
export function Stat({ label, value, tone, active, onClick, Icon }) {
  return <button type="button" onClick={onClick} aria-pressed={active} className={`card flex items-center gap-3 p-4 text-right transition ${active ? "!border-[var(--ac)]" : "hover:-translate-y-0.5"}`}>
    <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl" style={tint(tone)}><Icon size={19} /></span>
    <span><span className="block text-2xl font-extrabold leading-none">{num(value)}</span><span className="mt-1 block text-xs text-[var(--mu)]">{label}</span></span>
  </button>;
}
export const Section = ({ title, hint, children }) => <section className="card space-y-4 p-4"><div><h3 className="text-xs font-bold text-[var(--mu)]">{title}</h3>{hint && <p className="mt-1 text-[11px] leading-5 text-[var(--mu)]">{hint}</p>}</div>{children}</section>;

/** Number input showing grouped digits; `value` is a string of ASCII digits. */
export function NumInput({ value, onChange, placeholder, suffix, ...rest }) {
  const shown = value === "" ? "" : Number(value).toLocaleString("en-US");
  return <div className="relative"><input {...rest} dir="ltr" inputMode="numeric" className={`inp ${suffix ? "!pr-14" : ""}`} value={shown} placeholder={placeholder} onChange={(e) => onChange(digits(e.target.value).replace(/^0+(?=\d)/, ""))} />
    {suffix && <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[11px] font-bold text-[var(--mu)]">{suffix}</span>}</div>;
}

/** Right-side drawer with dirty-guard on close, sticky footer and server-error slot. */
export function Drawer({ title, subtitle, icon, dirty, busy, onClose, children, footer, error }) {
  const close = async () => { if (busy) return; if (dirty && !(await confirmDialog("تغییرات ذخیره‌نشده از بین می‌رود. بسته شود؟", { title: "بستن بدون ذخیره", danger: true, ok: "بستن" }))) return; onClose(); };
  return <div className="fixed inset-0 z-50" onKeyDown={(e) => e.key === "Escape" && close()}>
    <div className="pv-fade absolute inset-0 bg-black/55" onClick={close} />
    <aside role="dialog" aria-modal="true" aria-label={title} dir="rtl" className="pv-drawer absolute inset-y-0 right-0 flex w-full max-w-xl flex-col border-l border-[var(--ln)] bg-[var(--bg)] shadow-2xl">
      <header className="flex items-center gap-3 border-b border-[var(--ln)] bg-[var(--sf)] px-5 py-4">
        {icon}
        <div className="min-w-0 flex-1"><h2 className="truncate text-lg font-extrabold">{title}</h2>{subtitle && <p className="mt-0.5 truncate text-xs text-[var(--mu)]">{subtitle}</p>}</div>
        {dirty && <span className="badge b-wn">تغییرات ذخیره‌نشده</span>}
        <button className="btn btn-g !px-2" aria-label="بستن" onClick={close} disabled={busy}><X size={16} /></button>
      </header>
      <div className="flex-1 space-y-5 overflow-y-auto p-5">{children}</div>
      <footer className="border-t border-[var(--ln)] bg-[var(--sf)] px-5 py-3">
        {error && <p role="alert" className="mb-3 rounded-lg bg-[var(--bdb)] p-3 text-xs leading-6 text-[var(--bd)]">{error}</p>}
        <div className="flex flex-wrap items-center gap-2">{footer}<button className="btn btn-g !py-2 !text-sm" onClick={close} disabled={busy}>انصراف</button></div>
      </footer>
    </aside>
  </div>;
}
export const Saved = ({ on }) => on ? <span className="inline-flex items-center gap-1 text-xs font-bold text-[var(--ok)]"><Check size={14} />ذخیره شد</span> : null;
