// Account inquiry (استعلام): ONE component for the customer ("my accounts") and the reseller-store owner ("all my customers' accounts").
// The scope is decided by Core from the login (customer: own accounts only; reseller: the LIST is only his own accounts, a
// SEARCH also finds his own store's customers' accounts); this file only renders what Core returns. Expiry/usage are read live from the VPN panel through Core's /refresh endpoint.
import { useEffect, useMemo, useRef, useState } from "react";
import { RefreshCw, Search, X, ChevronLeft, ChevronRight, Gauge, Loader2 } from "lucide-react";
import { SubscriptionCard } from "./Subscription.jsx";
import { Empty, Loading, fa, fd } from "./ui.jsx";

const PAGE = 12;
const gb = (b) => (b ? (b / 1073741824).toFixed(1) : "0");
const CHIPS = [["", "همه", "total"], ["active", "فعال", "active"], ["expiring", "رو‌به‌اتمام", "expiring"], ["expired", "منقضی", "expired"]];
const HEALTH = {
  active: ["فعال", "bg-mint-soft text-mint"], expiring: ["رو‌به‌اتمام", "bg-accent-soft text-ink"], expired: ["منقضی", "bg-danger-soft text-danger"],
  depleted: ["حجم تمام‌شده", "bg-danger-soft text-danger"], disabled: ["غیرفعال", "bg-surface2 text-muted"],
};
export const HealthBadge = ({ health }) => { const [l, t] = HEALTH[health] || [health || "—", "bg-surface2 text-muted"]; return <span className={`badge ${t}`}><span className="h-1.5 w-1.5 rounded-full bg-current" />{l}</span>; };

function Card({ a, owner, base, coreFetch, notify, extra, onChange }) {
  const [busy, setBusy] = useState(false);
  const pct = a.usage_percent ?? 0;
  const refresh = async () => {
    setBusy(true);
    try { const r = await coreFetch(`${base}/${a.id}/refresh`, { method: "POST" }); if (!r.ok) throw 0; onChange(await r.json()); notify?.("از پنل بروزرسانی شد"); } catch { notify?.("بروزرسانی از پنل انجام نشد"); }
    setBusy(false);
  };
  return <div className="card">
    <div className="flex items-center justify-between gap-2"><b className="latin break-all">{a.username}</b><HealthBadge health={a.health} /></div>
    {owner && a.holder_label && <div className="mt-1 text-xs text-muted">{a.holder_label}</div>}
    <div className="mt-4 flex items-center justify-between text-xs text-muted"><span>انقضا: {a.expires_at ? fd(a.expires_at) : "نامحدود"}</span>{a.days_left != null && <b className="text-ink">{fa(a.days_left)} روز مانده</b>}</div>
    <div className="mt-3 h-2 overflow-hidden rounded-full bg-surface2"><div className={`h-full rounded-full ${pct > 85 ? "bg-danger" : "bg-coral"}`} style={{ width: `${pct}%` }} /></div>
    <div className="mt-1 text-xs text-muted">{gb(a.traffic_used_bytes)} از {a.traffic_limit_bytes ? gb(a.traffic_limit_bytes) : "∞"} گیگ</div>
    <SubscriptionCard account={a} coreFetch={coreFetch} notify={notify} qrPath={owner ? `${base}/${a.id}/qr.png` : undefined} />
    <button onClick={refresh} disabled={busy} className="btn-soft mt-2 w-full !py-2 text-xs">{busy ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}بروزرسانی از پنل</button>
    {extra}
  </div>;
}

/**
 * props: base  = "/api/v1/vpn-accounts" (customer) | "/api/v1/stores/{id}/reseller/accounts" (owner)
 *        owner = show customer names + search by customer
 *        renderExtra(account, replace) = per-card actions (the customer's renew button)
 *        reloadKey = bump to refetch after a renewal
 */
export default function AccountInquiry({ coreFetch, base, owner = false, notify, renderExtra, reloadKey = 0, emptyText, emptyAction }) {
  const [state, setState] = useState("");
  const [input, setInput] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const [rows, setRows] = useState(null);
  const [more, setMore] = useState(false);
  const [counts, setCounts] = useState(null);
  const seq = useRef(0);
  useEffect(() => { const t = setTimeout(() => { setQ(input.trim()); setPage(0); }, 350); return () => clearTimeout(t); }, [input]);
  useEffect(() => {
    const my = ++seq.current;
    const p = new URLSearchParams({ limit: String(PAGE + 1), offset: String(page * PAGE) });
    if (state) p.set("state", state);
    if (q) p.set("q", q);
    setRows(null);
    Promise.all([coreFetch(`${base}?${p}`).then((r) => (r.ok ? r.json() : Promise.reject())), coreFetch(`${base}/summary`).then((r) => (r.ok ? r.json() : null)).catch(() => null)])
      .then(([list, sum]) => { if (my !== seq.current) return; setMore(list.length > PAGE); setRows(list.slice(0, PAGE)); setCounts(sum); })
      .catch(() => { if (my === seq.current) { setRows([]); setMore(false); } });
  }, [base, state, q, page, reloadKey]);
  const replace = (n) => setRows((cur) => (cur || []).map((x) => (x.id === n.id ? { ...x, ...n } : x)));
  const filtered = useMemo(() => Boolean(state || q), [state, q]);
  if (!owner && counts && !counts.total && !filtered && rows && !rows.length) return <Empty icon={Gauge} text={emptyText || "اکانتی وجود ندارد."}>{emptyAction}</Empty>;
  return <div className="space-y-4">
    <div className="flex flex-wrap items-center gap-2" role="tablist" aria-label="فیلتر وضعیت">
      {CHIPS.map(([k, label, ck]) => <button key={k || "all"} role="tab" aria-selected={state === k} onClick={() => { setState(k); setPage(0); }} className={`rounded-full px-4 py-2 text-xs font-bold transition ${state === k ? "bg-primary text-onprimary shadow-soft" : "bg-surface text-muted ring-1 ring-line hover:bg-surface2 hover:text-ink"}`}>{label}{counts ? ` (${fa(counts[ck])})` : ""}</button>)}
    </div>
    <div className="relative"><Search size={16} className="pointer-events-none absolute right-3.5 top-1/2 -translate-y-1/2 text-muted" />
      <input value={input} onChange={(e) => setInput(e.target.value)} className="input !pr-10 !pl-10" placeholder={owner ? "جستجوی اکانت مشتریان: نام اکانت، نام یا ایمیل مشتری" : "جستجو در نام اکانت"} aria-label="جستجوی اکانت" maxLength={64} />
      {input && <button onClick={() => setInput("")} aria-label="پاک‌کردن جستجو" className="absolute left-3 top-1/2 -translate-y-1/2 text-muted"><X size={16} /></button>}</div>
    {owner && !q && counts?.note && <p className="text-xs text-muted">{counts.note}</p>}
    {rows === null ? <Loading rows={2} /> : !rows.length ? <Empty icon={Search} text={owner && !q && !state ? (emptyText || "اکانتی ندارید.") : "نتیجه‌ای پیدا نشد."} /> :
      <div className="grid gap-4 md:grid-cols-2">{rows.map((a) => <Card key={a.id} a={a} owner={owner} base={base} coreFetch={coreFetch} notify={notify} onChange={replace} extra={renderExtra?.(a, replace)} />)}</div>}
    {(page > 0 || more) && <div className="flex items-center justify-center gap-3 pt-2">
      <button disabled={page === 0} onClick={() => setPage(page - 1)} className="btn-ghost"><ChevronRight size={14} />قبلی</button>
      <span className="text-xs text-muted">صفحه {fa(page + 1)}</span>
      <button disabled={!more} onClick={() => setPage(page + 1)} className="btn-ghost">بعدی<ChevronLeft size={14} /></button></div>}
  </div>;
}
