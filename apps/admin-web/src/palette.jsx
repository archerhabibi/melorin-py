import { useEffect, useMemo, useRef, useState } from "react";
import { CornerDownLeft, Search } from "lucide-react";

// Ctrl/⌘+K command palette: items = [{ name, hint, Icon, run }]
export function Palette({ items, onClose }) {
  const [q, setQ] = useState(""); const [i, setI] = useState(0); const ref = useRef();
  const list = useMemo(() => items.filter((x) => `${x.name} ${x.hint || ""}`.toLowerCase().includes(q.trim().toLowerCase())), [items, q]);
  useEffect(() => setI(0), [q]);
  useEffect(() => ref.current?.querySelector("[data-on]")?.scrollIntoView({ block: "nearest" }), [i]);
  const key = (e) => {
    if (e.key === "Escape") onClose();
    else if (e.key === "ArrowDown") { e.preventDefault(); setI((x) => Math.min(x + 1, list.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setI((x) => Math.max(x - 1, 0)); }
    else if (e.key === "Enter" && list[i]) { onClose(); list[i].run(); }
  };
  return <div className="fixed inset-0 z-50 grid place-items-start bg-black/55 p-4 pt-[12vh]" onClick={onClose} onKeyDown={key}>
    <div role="dialog" aria-modal="true" aria-label="جستجوی سریع" dir="rtl" className="card rise mx-auto w-full max-w-lg overflow-hidden" onClick={(e) => e.stopPropagation()}>
      <label className="flex items-center gap-3 border-b border-[var(--ln)] px-4"><Search size={18} className="text-[var(--mu)]" /><input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="برو به بخش یا اجرای عملیات…" className="w-full bg-transparent py-4 text-sm outline-none" /></label>
      <ul ref={ref} className="max-h-80 overflow-auto p-2">{list.length ? list.map((x, n) => <li key={x.name}><button data-on={n === i ? "" : undefined} onMouseEnter={() => setI(n)} onClick={() => { onClose(); x.run(); }} className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm ${n === i ? "bg-[var(--mb)] font-bold" : ""}`}><x.Icon size={17} className="text-[var(--mu)]" />{x.name}<span className="mr-auto text-xs font-normal text-[var(--mu)]">{x.hint}</span>{n === i && <CornerDownLeft size={14} className="text-[var(--mu)]" />}</button></li>) : <li className="p-8 text-center text-sm text-[var(--mu)]">موردی پیدا نشد</li>}</ul>
    </div>
  </div>;
}
