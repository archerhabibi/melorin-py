import { useEffect, useRef, useState } from "react";
import { Bell, ChevronDown, Gauge, KeyRound, LifeBuoy, LogOut, Package, Store, Wallet as WalletIcon, ArrowRight, Link2, Pencil, Plus, RefreshCw, Send, X } from "lucide-react";
import { GoogleSignInButton } from "./GoogleSignIn.jsx";
import { SubscriptionCard } from "./Subscription.jsx";
import { Empty, Loading, PageTitle, StatusBadge, fa, fd } from "./ui.jsx";
const gb = (b) => (b ? (b / 1073741824).toFixed(1) : "0");
const J = { "Content-Type": "application/json" };
const tabs = [["orders", "سفارش‌ها", Package], ["vpn", "اکانت‌های VPN", Gauge], ["wallet", "کیف پول", WalletIcon], ["tickets", "تیکت‌ها", LifeBuoy], ["notifications", "اعلان‌ها", Bell], ["profile", "پروفایل و امنیت", KeyRound]];
const card = "card";
const btn = "btn-primary";
const inp = "input";


function Orders({ orders }) {
  if (!orders.length) return <Empty text="هنوز سفارشی ثبت نشده است." />;
  return <div className="space-y-3">{orders.map((o) => <div key={o.id} className={`${card} flex flex-wrap items-center justify-between gap-3`}><div><div className="latin font-extrabold">{o.number}</div><div className="mt-1 text-xs text-muted">{fd(o.created_at)}</div></div><div className="font-bold">{fa(o.total)} {o.currency}</div><StatusBadge status={o.status} /></div>)}</div>;
}

function Renew({ account, coreFetch, storeId, notify, reload, onClose }) {
  const [pk, setPk] = useState(null);
  const [sel, setSel] = useState(null);
  const [quote, setQuote] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { coreFetch(`/api/v1/stores/${storeId}/accounts/${account.id}/renewal-packages`).then((r) => r.ok ? r.json() : Promise.reject(r)).then((d) => setPk(Array.isArray(d) ? d : d.items || [])).catch(async (r) => { setPk([]); notify(r?.json ? await msgOf(r, "پکیج تمدید دریافت نشد") : "پکیج تمدید دریافت نشد"); }); }, [account.id]);
  async function pick(p) {
    setSel(p); setQuote(null); setBusy(true);
    try { const r = await coreFetch(`/api/v1/stores/${storeId}/checkout/quote`, { method: "POST", headers: J, body: JSON.stringify({ product_id: p.product_id, vpn_account_id: account.id }) }); if (!r.ok) { setSel(null); return notify(await msgOf(r, "پیش‌فاکتور دریافت نشد")); } setQuote(await r.json()); }
    catch { setSel(null); notify("پیش‌فاکتور دریافت نشد"); } finally { setBusy(false); }
  }
  async function buy() {
    setBusy(true);
    try { const r = await coreFetch(`/api/v1/stores/${storeId}/orders`, { method: "POST", headers: { ...J, "Idempotency-Key": `web-renew-${crypto.randomUUID()}` }, body: JSON.stringify({ product_id: sel.product_id, payment_method: "wallet", kind: "renewal", vpn_account_id: account.id }) }); if (!r.ok) return notify(await msgOf(r, "تمدید ناموفق بود")); notify("تمدید ثبت شد"); reload?.(); onClose(); }
    finally { setBusy(false); }
  }
  return <div className="mt-4 rounded-xl bg-surface2 p-3 text-sm">
    <div className="flex items-center justify-between"><b>تمدید اکانت</b><button onClick={onClose} aria-label="بستن" className="text-muted"><X size={16} /></button></div>
    {pk === null ? <Loading rows={1} /> : !pk.length ? <p className="mt-2 text-xs text-muted">پکیجی برای تمدید این اکانت موجود نیست.</p> : <div className="mt-2 space-y-2">{pk.map((p) => <button key={p.product_id} disabled={busy} onClick={() => pick(p)} aria-pressed={sel?.product_id === p.product_id} className={`flex w-full items-center justify-between gap-2 rounded-lg border px-3 py-2 text-right ${sel?.product_id === p.product_id ? "border-coral" : "border-line"}`}><span><b>{p.name}</b><span className="mr-2 text-xs text-muted">{p.duration_days ? fa(p.duration_days) : "؟"} روز · {p.traffic_gb ? fa(p.traffic_gb) : "؟"} گیگ</span></span><b>{fa(p.price)} {p.currency}</b></button>)}</div>}
    {quote && <div className="mt-3 flex items-center justify-between gap-3 border-t border-line pt-3"><span>مبلغ نهایی: <b>{fa(quote.total)} {quote.currency}</b>{!quote.sufficient_funds && <span className="mr-2 text-xs text-danger">موجودی کافی نیست</span>}</span><button disabled={busy || !quote.sufficient_funds} onClick={buy} className="btn-primary !px-4 !py-2 text-xs">پرداخت از کیف پول و تمدید</button></div>}
  </div>;
}

function Vpn({ coreFetch, storeId, notify, reload }) {
  const [rows, setRows] = useState(null);
  const [renew, setRenew] = useState(null);
  useEffect(() => { coreFetch("/api/v1/vpn-accounts").then((r) => r.json()).then(setRows).catch(() => setRows([])); }, []);
  if (!rows) return <Loading rows={2} />;
  if (!rows.length) return <Empty icon={Gauge} text="اکانتی ندارید. از بخش سرویس‌ها خرید کنید."><a href="#plans" className="btn-primary mt-5">دیدن سرویس‌ها</a></Empty>;
  return <div className="grid gap-4 md:grid-cols-2">{rows.map((a) => {
    const pct = a.traffic_limit_bytes ? Math.min(100, (a.traffic_used_bytes / a.traffic_limit_bytes) * 100) : 0;
    return <div key={a.id} className={card}>
      <div className="flex items-center justify-between"><b className="latin">{a.username}</b><StatusBadge status={a.status} /></div>
      <div className="mt-4 text-xs text-muted">انقضا: {fd(a.expires_at)}</div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-surface2"><div className={`h-full rounded-full ${pct > 85 ? "bg-danger" : "bg-coral"}`} style={{ width: `${pct}%` }} /></div>
      <div className="mt-1 text-xs text-muted">{gb(a.traffic_used_bytes)} از {a.traffic_limit_bytes ? gb(a.traffic_limit_bytes) : "∞"} گیگ</div>
      <SubscriptionCard account={a} coreFetch={coreFetch} notify={notify} />
      <button onClick={() => setRenew(renew === a.id ? null : a.id)} className="btn-soft mt-2 w-full"><RefreshCw size={16} />تمدید</button>
      {renew === a.id && <Renew account={a} coreFetch={coreFetch} storeId={storeId} notify={notify} reload={reload} onClose={() => setRenew(null)} />}
    </div>;
  })}</div>;
}

function Wallet({ coreFetch, storeId, wallet, reload, notify }) {
  const [tx, setTx] = useState([]);
  const [amount, setAmount] = useState("");
  const [pay, setPay] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = () => coreFetch(`/api/v1/stores/${storeId}/wallet/transactions`).then((r) => r.json()).then((d) => setTx(Array.isArray(d) ? d : d.items || [])).catch(() => {});
  useEffect(() => { load(); }, [storeId]);
  async function topup() {
    setBusy(true);
    try {
      const r = await coreFetch(`/api/v1/stores/${storeId}/wallet/topups`, { method: "POST", headers: { ...J, "Idempotency-Key": `topup-${crypto.randomUUID()}` }, body: JSON.stringify({ amount: Number(amount), provider: "manual_card" }) });
      if (!r.ok) throw 0;
      const p = await r.json(); setPay(p);
      if (p.instructions?.redirect_url) window.location.href = p.instructions.redirect_url;
    } catch (e) { notify(e?.message || "ایجاد درخواست شارژ ناموفق بود"); } finally { setBusy(false); }
  }
  async function receipt(file) {
    const fd_ = new FormData(); fd_.append("file", file);
    const r = await coreFetch(`/api/v1/payments/${pay.id}/receipt`, { method: "POST", body: fd_ });
    if (r.ok) { notify("رسید ارسال شد؛ پس از تأیید شارژ می‌شود"); setPay(null); setAmount(""); reload(); load(); } else notify("ارسال رسید ناموفق بود");
  }
  return <div className="grid gap-5 md:grid-cols-[.8fr_1.2fr]">
    <div className="space-y-4">
      <div className="rounded-2xl bg-hero p-6 text-white"><div className="text-sm text-white/60">موجودی</div><div className="mt-2 text-3xl font-extrabold">{fa(wallet?.balance)} <span className="text-sm font-normal">{wallet?.currency}</span></div></div>
      <div className={card}><h4 className="font-extrabold">شارژ کیف پول</h4>
        {!pay ? <><input className={`${inp} mt-3`} inputMode="numeric" placeholder="مبلغ" value={amount} onChange={(e) => setAmount(e.target.value.replace(/\D/g, ""))} /><button disabled={busy || !Number(amount)} onClick={topup} className={`${btn} mt-3 w-full`}>ایجاد درخواست</button></>
          : <><div className="mt-3 rounded-xl bg-accent-soft p-3 text-sm leading-7">{pay.instructions?.card_number ? <>کارت: <b className="latin">{pay.instructions.card_number}</b><br />{pay.instructions.holder}</> : "دستورالعمل پرداخت را دنبال کنید."}<br />مبلغ: {fa(pay.amount)} {pay.currency}</div>
            <label className="mt-3 block cursor-pointer rounded-xl border border-dashed border-line p-4 text-center text-sm font-bold">آپلود رسید<input type="file" accept="image/*,.pdf" className="hidden" onChange={(e) => e.target.files[0] && receipt(e.target.files[0])} /></label></>}
      </div></div>
    <div className={card}><h4 className="font-extrabold">تراکنش‌ها</h4>{tx.length ? <div className="mt-3 divide-y divide-line">{tx.map((t) => <div key={t.transaction_id} className="flex justify-between py-3 text-sm"><div><div className="font-bold">{t.kind}</div><div className="text-xs text-muted">{t.memo || ""} · {fd(t.created_at)}</div></div><b className={t.amount < 0 ? "text-danger" : "text-mint"} dir="ltr">{fa(t.amount)}</b></div>)}</div> : <p className="mt-3 text-sm text-muted">تراکنشی ثبت نشده.</p>}</div>
  </div>;
}

const PRIO = [["low", "کم"], ["normal", "عادی"], ["high", "مهم"]];
const PRIO_LABEL = { low: "کم", normal: "عادی", high: "مهم", urgent: "فوری" };
const timeOnly = (d) => new Date(d).toLocaleTimeString("fa-IR", { hour: "2-digit", minute: "2-digit" });
const dayLabel = (d) => new Date(d).toLocaleDateString("fa-IR", { dateStyle: "full" });
async function msgOf(r, fallback) { try { const d = await r.json(); return d?.error?.message || (typeof d?.detail === "string" ? d.detail : "") || fallback; } catch { return fallback; } }

function TicketThread({ t, coreFetch, notify, onBack, onChanged }) {
  const [msgs, setMsgs] = useState(null);
  const [ticket, setTicket] = useState(t);
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(null); // message id
  const [draft, setDraft] = useState("");
  const [subj, setSubj] = useState(null);
  const end = useRef(null);
  const last = useRef(0);
  const load = () => coreFetch(`/api/v1/tickets/${t.id}/messages`).then((r) => r.json()).then((x) => Array.isArray(x) && setMsgs(x)).catch(() => {});
  useEffect(() => { load(); const iv = setInterval(() => !document.hidden && load(), 12000); return () => clearInterval(iv); }, [t.id]);
  useEffect(() => { const n = msgs?.length || 0; if (n !== last.current) { end.current?.scrollIntoView({ behavior: last.current ? "smooth" : "auto", block: "end" }); last.current = n; } }, [msgs]);
  const me = (m) => !m.is_staff; // customer-side view: only the customer's own messages are editable
  async function patchTicket(body, ok) {
    setBusy(true);
    try { const r = await coreFetch(`/api/v1/tickets/${t.id}`, { method: "PATCH", headers: J, body: JSON.stringify(body) }); if (!r.ok) return notify(await msgOf(r, "ذخیره ناموفق بود")); setTicket(await r.json()); onChanged(); ok && notify(ok); }
    finally { setBusy(false); }
  }
  async function send() {
    setBusy(true);
    try { const r = await coreFetch(`/api/v1/tickets/${t.id}/messages`, { method: "POST", headers: J, body: JSON.stringify({ body: reply.trim() }) }); if (!r.ok) return notify(await msgOf(r, "ارسال ناموفق بود")); setReply(""); setTicket((x) => ({ ...x, status: "open" })); await load(); onChanged(); }
    finally { setBusy(false); }
  }
  async function saveEdit(m) {
    setBusy(true);
    try { const r = await coreFetch(`/api/v1/tickets/${t.id}/messages/${m.id}`, { method: "PATCH", headers: J, body: JSON.stringify({ body: draft.trim() }) }); if (!r.ok) return notify(await msgOf(r, "ویرایش ناموفق بود")); setEditing(null); await load(); notify("پیام ویرایش شد"); }
    finally { setBusy(false); }
  }
  const closed = ticket.status === "closed";
  let prev = "";
  return <div className={`${card} !p-0 flex flex-col overflow-hidden`}>
    <div className="border-b border-line p-4">
      <div className="flex items-start gap-3">
        <button onClick={onBack} aria-label="بازگشت" className="grid h-9 w-9 shrink-0 place-items-center rounded-full ring-1 ring-line hover:bg-surface2"><ArrowRight size={16} /></button>
        <div className="min-w-0 flex-1">
          {subj === null ? <div className="flex items-center gap-2"><h4 className="truncate font-extrabold">{ticket.subject}</h4>
            <button aria-label="ویرایش موضوع" title="ویرایش موضوع" onClick={() => setSubj(ticket.subject)} className="grid h-7 w-7 place-items-center rounded-full text-muted hover:bg-surface2"><Pencil size={13} /></button></div>
            : <div className="flex gap-2"><input autoFocus aria-label="موضوع تیکت" className={inp} maxLength={200} value={subj} onChange={(e) => setSubj(e.target.value)} onKeyDown={(e) => { if (e.key === "Escape") setSubj(null); if (e.key === "Enter" && subj.trim().length >= 2) { patchTicket({ subject: subj }, "موضوع ویرایش شد"); setSubj(null); } }} />
              <button disabled={subj.trim().length < 2 || busy} className="btn-primary" onClick={() => { patchTicket({ subject: subj }, "موضوع ویرایش شد"); setSubj(null); }}>ذخیره</button></div>}
          <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-muted"><span className="latin font-bold">#{ticket.number}</span><StatusBadge status={ticket.status} /><span>اولویت: {PRIO_LABEL[ticket.priority] || "عادی"}</span><span>· {fd(ticket.created_at)}</span></div>
        </div>
        <button disabled={busy} onClick={() => patchTicket({ status: closed ? "open" : "closed" }, closed ? "تیکت دوباره باز شد" : "تیکت بسته شد")} className="rounded-xl border border-line px-3 py-2 text-xs font-bold hover:bg-surface2 disabled:opacity-50">{closed ? "بازگشایی" : "بستن تیکت"}</button>
      </div>
    </div>
    <div className="max-h-[55vh] min-h-[16rem] space-y-4 overflow-y-auto bg-surface2/50 p-4" role="log" aria-live="polite">
      {msgs === null ? <Loading rows={2} /> : msgs.map((m) => {
        const day = dayLabel(m.created_at); const head = day !== prev; prev = day;
        return <div key={m.id} className="space-y-3">
          {head && <div className="flex items-center gap-3 text-[11px] text-muted"><span className="h-px flex-1 bg-line" />{day}<span className="h-px flex-1 bg-line" /></div>}
          <div className={`group flex ${m.is_staff ? "justify-end" : ""}`}>
            <div className={`max-w-[88%] rounded-2xl p-3 text-sm leading-7 ${m.is_staff ? "rounded-tl-sm bg-mint-soft" : "rounded-tr-sm bg-surface ring-1 ring-line"}`}>
              <div className="mb-0.5 text-[11px] font-bold text-muted">{m.is_staff ? "🎧 پشتیبانی" : "شما"}</div>
              {editing === m.id ? <div className="space-y-2"><textarea autoFocus rows={3} maxLength={10000} dir="auto" className={`${inp} min-w-[min(70vw,24rem)]`} value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => { if (e.key === "Escape") setEditing(null); if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && draft.trim()) saveEdit(m); }} />
                <div className="flex gap-2"><button disabled={busy || !draft.trim() || draft.trim() === m.body} onClick={() => saveEdit(m)} className="btn-primary !px-4 !py-2 text-xs">ذخیرهٔ ویرایش</button><button onClick={() => setEditing(null)} className="rounded-xl border border-line px-3 text-xs font-bold">انصراف</button></div></div>
                : <p dir="auto" className="whitespace-pre-wrap break-words">{m.body}</p>}
              <div className="mt-1 flex items-center gap-2 text-[10px] text-muted"><span>{timeOnly(m.created_at)}</span>{m.edited_at && <span className="italic">· ویرایش‌شده</span>}
                {me(m) && editing !== m.id && !closed && <button onClick={() => { setEditing(m.id); setDraft(m.body); }} className="mr-auto inline-flex items-center gap-1 font-bold text-coral opacity-0 transition focus-visible:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100"><Pencil size={11} />ویرایش</button>}</div>
            </div></div></div>;
      })}
      {ticket.status === "answered" && <p className="text-center text-xs text-muted">پشتیبانی پاسخ داده است. اگر مشکل ادامه دارد همین‌جا پیام بدهید.</p>}
      <div ref={end} />
    </div>
    {closed ? <div className="flex items-center justify-between gap-3 border-t border-line p-4 text-sm"><span className="text-muted">این تیکت بسته شده است.</span><button disabled={busy} onClick={() => patchTicket({ status: "open" }, "تیکت دوباره باز شد")} className="btn-primary">بازگشایی تیکت</button></div>
      : <div className="flex items-end gap-2 border-t border-line p-3">
        <textarea rows={1} dir="auto" maxLength={10000} aria-label="پیام شما" className={`${inp} max-h-40 resize-none`} placeholder="پیام خود را بنویسید… (Ctrl+Enter برای ارسال)" value={reply} onChange={(e) => setReply(e.target.value)} onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && reply.trim() && !busy) send(); }} />
        <button disabled={busy || !reply.trim()} onClick={send} className="btn-primary h-11 shrink-0" aria-label="ارسال"><Send size={16} className="-scale-x-100" /></button></div>}
  </div>;
}

function Tickets({ coreFetch, storeId, notify }) {
  const [list, setList] = useState(null);
  const [sel, setSel] = useState(null);
  const [creating, setCreating] = useState(false);
  const [filter, setFilter] = useState("all");
  const [form, setForm] = useState({ subject: "", body: "", priority: "normal" });
  const [busy, setBusy] = useState(false);
  const load = () => coreFetch(`/api/v1/stores/${storeId}/tickets`).then((r) => r.json()).then((x) => setList(Array.isArray(x) ? x : [])).catch(() => setList((x) => x || []));
  useEffect(() => { load(); }, [storeId]);
  async function create() {
    setBusy(true);
    try {
      const r = await coreFetch(`/api/v1/stores/${storeId}/tickets`, { method: "POST", headers: J, body: JSON.stringify({ ...form, subject: form.subject.trim(), body: form.body.trim() }) });
      if (!r.ok) return notify(await msgOf(r, "ثبت تیکت ناموفق بود"));
      const t = await r.json(); setForm({ subject: "", body: "", priority: "normal" }); setCreating(false); notify(`تیکت #${t.number} ثبت شد`); await load(); setSel(t);
    } finally { setBusy(false); }
  }
  if (sel) return <TicketThread key={sel.id} t={sel} coreFetch={coreFetch} notify={notify} onBack={() => { setSel(null); load(); }} onChanged={load} />;
  if (list === null) return <Loading rows={3} />;
  const shown = list.filter((t) => filter === "all" || (filter === "closed" ? t.status === "closed" : t.status !== "closed"));
  return <div className="space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div role="radiogroup" aria-label="فیلتر تیکت‌ها" className="inline-flex gap-1 rounded-xl bg-surface2 p-1">{[["all", "همه"], ["active", "فعال"], ["closed", "بسته"]].map(([v, l]) => <button key={v} role="radio" aria-checked={filter === v} onClick={() => setFilter(v)} className={`rounded-lg px-3 py-1.5 text-xs font-bold transition ${filter === v ? "bg-surface text-ink shadow-soft" : "text-muted"}`}>{l}</button>)}</div>
      <button onClick={() => setCreating((x) => !x)} className="btn-primary">{creating ? <><X size={16} />بستن فرم</> : <><Plus size={16} />تیکت جدید</>}</button>
    </div>
    {creating && <div className={card}>
      <h4 className="font-extrabold">تیکت جدید</h4>
      <div className="mt-3 grid gap-3 sm:grid-cols-[1fr_10rem]">
        <input className={inp} placeholder="موضوع (مثلاً: اتصال برقرار نمی‌شود)" maxLength={200} value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} />
        <select aria-label="اولویت" className={inp} value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>{PRIO.map(([v, l]) => <option key={v} value={v}>اولویت: {l}</option>)}</select>
      </div>
      <textarea rows={5} dir="auto" maxLength={10000} className={`${inp} mt-3`} placeholder="توضیحات کامل مشکل یا درخواست…" value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} />
      <div className="mt-3 flex items-center justify-between gap-3"><span className="text-xs text-muted">پاسخ پشتیبانی در تلگرام هم به شما اطلاع داده می‌شود.</span>
        <button disabled={busy || form.subject.trim().length < 2 || !form.body.trim()} onClick={create} className="btn-primary">ثبت تیکت</button></div>
    </div>}
    {shown.length ? <div className="space-y-3">{shown.map((t) => <button key={t.id} onClick={() => setSel(t)} className={`${card} flex w-full items-center justify-between gap-3 text-right transition hover:-translate-y-0.5`}>
      <div className="min-w-0"><div className="flex items-center gap-2"><span className="latin rounded-md bg-surface2 px-1.5 py-0.5 text-[11px] font-bold text-muted">#{t.number}</span><b className="truncate">{t.subject}</b></div>
        <div className="mt-1 text-xs text-muted">{fd(t.updated_at)}{t.priority && t.priority !== "normal" ? ` · اولویت ${PRIO_LABEL[t.priority]}` : ""}</div></div>
      <StatusBadge status={t.status} /></button>)}</div>
      : <Empty icon={LifeBuoy} text={list.length ? "تیکتی با این فیلتر وجود ندارد." : "هنوز تیکتی ثبت نکرده‌اید."}>{!list.length && <button onClick={() => setCreating(true)} className="btn-primary mt-5">ثبت اولین تیکت</button>}</Empty>}
  </div>;
}


function Notifications({ coreFetch, notify, onCount }) {
  const [d, setD] = useState(null);
  const load = () => coreFetch("/api/v1/me/notifications").then((r) => r.json()).then((x) => { setD(x); onCount?.(x.unread); }).catch(() => setD({ items: [], unread: 0 }));
  useEffect(() => { load(); }, []);
  const read = async (n) => { if (!n.read) { await coreFetch(`/api/v1/me/notifications/${n.id}/read`, { method: "POST" }); load(); } };
  const all = async () => { const r = await coreFetch("/api/v1/me/notifications/read-all", { method: "POST" }); r.ok ? load() : notify("ناموفق بود"); };
  if (!d) return <Loading rows={3} />;
  return <div><div className="mb-3 flex items-center justify-between"><span className="text-sm text-muted">{fa(d.unread)} اعلان خوانده‌نشده</span><button disabled={!d.unread} onClick={all} className="rounded-lg border border-line px-3 py-1.5 text-xs font-bold disabled:opacity-40">علامت‌گذاری همه</button></div>
    {d.items.length ? <div className="space-y-2">{d.items.map((n) => <button key={n.id} onClick={() => read(n)} className={`${card} block w-full text-right ${n.read ? "opacity-60" : "border-coral"}`}><div className="flex justify-between"><b>{n.title}</b>{!n.read && <span className="h-2 w-2 rounded-full bg-coral" />}</div><p className="mt-1 text-sm leading-7 text-muted">{n.body}</p><div className="mt-1 text-[10px] text-muted">{fd(n.created_at)}</div></button>)}</div> : <Empty text="اعلانی ندارید." />}</div>;
}

function Profile({ coreFetch, account, notify, reload }) {
  const [name, setName] = useState(account?.display_name || "");
  const [link, setLink] = useState(null);
  const [pw, setPw] = useState("");
  const [totp, setTotp] = useState(null);
  const [code, setCode] = useState("");
  const post = (p, body) => coreFetch(p, { method: "POST", headers: J, body: body ? JSON.stringify(body) : undefined });
  const copy = (t) => navigator.clipboard?.writeText(t).then(() => notify("کپی شد"));
  async function saveName() { const r = await coreFetch("/api/v1/me", { method: "PATCH", headers: J, body: JSON.stringify({ display_name: name }) }); notify(r.ok ? "ذخیره شد" : "ذخیره ناموفق بود"); r.ok && reload(); }
  async function tg() { const r = await post("/api/v1/me/link-codes/telegram"); r.ok ? setLink(await r.json()) : notify("ساخت کد ناموفق بود"); }
  async function linkGoogle(idToken) { const r = await post("/api/v1/me/identities/google", { id_token: idToken }); if (r.ok) { notify("حساب گوگل متصل شد"); reload(); } else notify(r.status === 409 ? "این حساب گوگل به حساب دیگری متصل است" : "اتصال گوگل ناموفق بود"); }
  const googleLinked = (account?.identities || []).some((i) => i.provider === "google");
  async function setPass() { const r = await post("/api/v1/me/password", { password: pw }); notify(r.ok ? "رمز عبور تنظیم شد" : "رمز نامعتبر است (حداقل ۸ کاراکتر)"); r.ok && setPw(""); }
  async function setup2fa() { const r = await post("/api/v1/me/2fa/setup"); r.ok ? setTotp(await r.json()) : notify("راه‌اندازی ناموفق بود"); }
  async function enable2fa() { const r = await post("/api/v1/me/2fa/enable", { code }); if (r.ok) { notify("۲FA فعال شد"); setTotp(null); setCode(""); reload(); } else notify("کد نادرست است"); }
  return <div className="grid gap-5 md:grid-cols-2">
    <div className={card}><h4 className="font-extrabold">پروفایل</h4><div className="mt-2 text-xs text-muted">{account?.email || "ایمیل ثبت نشده"}</div><input className={`${inp} mt-3`} value={name} onChange={(e) => setName(e.target.value)} placeholder="نام نمایشی" /><button onClick={saveName} className={`${btn} mt-3`}>ذخیره</button></div>
    <div className={card}><h4 className="font-extrabold">دعوت دوستان (رفرال)</h4><p className="mt-2 text-sm text-muted">کد دعوت شما:</p><div className="mt-2 flex gap-2"><code className="latin flex-1 rounded-xl bg-surface2 p-3 text-center font-bold">{account?.referral_code || "—"}</code><button onClick={() => copy(account?.referral_code)} className={btn}>کپی</button></div></div>
    <div className={card}><h4 className="font-extrabold">اتصال تلگرام</h4>{link ? <div className="mt-3 text-sm leading-7">کد: <b className="latin">{link.code}</b> (تا {Math.round(link.expires_in / 60)} دقیقه معتبر){link.telegram_deeplink && <a href={link.telegram_deeplink} target="_blank" rel="noreferrer" className={`${btn} mt-3 block text-center`}>باز کردن در تلگرام</a>}</div> : <button onClick={tg} className={`${btn} mt-3`}>ساخت کد اتصال</button>}</div>
    <div className={card}><h4 className="font-extrabold">اتصال گوگل</h4>{googleLinked ? <div className="mt-3 text-sm font-bold text-mint">✓ حساب گوگل به این حساب متصل است</div> : <><p className="mt-2 text-sm leading-7 text-muted">با اتصال گوگل، هم با تلگرام و هم با گوگل وارد همین حساب می‌شوید.</p><GoogleSignInButton onCredential={linkGoogle} text="continue_with" className="mt-3" /></>}</div>
    <div className={card}><h4 className="font-extrabold">امنیت</h4>
      <input type="password" dir="ltr" className={`${inp} mt-3`} value={pw} onChange={(e) => setPw(e.target.value)} placeholder="رمز عبور جدید" /><button disabled={pw.length < 8} onClick={setPass} className={`${btn} mt-3`}>تنظیم رمز</button>
      <div className="mt-5 border-t border-line pt-4 text-sm">{account?.totp_enabled ? <b className="text-mint">✓ ورود دومرحله‌ای فعال است</b> : totp ? <><div>این کلید را در برنامه Authenticator وارد کنید:</div><code dir="ltr" className="latin mt-2 block break-all rounded-xl bg-surface2 p-3 text-xs">{totp.secret}</code><input dir="ltr" className={`${inp} mt-3`} value={code} onChange={(e) => setCode(e.target.value)} placeholder="کد ۶ رقمی" /><button disabled={!code} onClick={enable2fa} className={`${btn} mt-3`}>فعال‌سازی</button></> : <button onClick={setup2fa} className={btn}>راه‌اندازی ورود دومرحله‌ای</button>}</div></div>
  </div>;
}

export default function Dashboard({ coreFetch, storeId, account, wallet, orders, reload, notify, onLogout }) {
  const [tab, setTab] = useState("orders");
  const [unread, setUnread] = useState(0);
  useEffect(() => { coreFetch("/api/v1/me/notifications?unread_only=true&limit=1").then((r) => r.ok ? r.json() : null).then((d) => d && setUnread(d.unread)).catch(() => {}); }, []);
  const name = account?.display_name || account?.email || "کاربر";
  const stats = [["موجودی کیف پول", wallet ? `${fa(wallet.balance)} ${wallet.currency || ""}` : "—", WalletIcon, "tab:wallet"], ["سفارش‌ها", fa(orders.length), Package, "tab:orders"], ["اعلان خوانده‌نشده", fa(unread), Bell, "tab:notifications"]];
  return <div className="mx-auto max-w-6xl px-5 py-10">
    <PageTitle eyebrow="حساب من" title={`سلام، ${name}`}>
      <a href="#/reseller" className="btn-soft btn-pill !py-2.5"><Store size={16} />پنل نماینده</a>
      <a href="#" className="btn-soft btn-pill !py-2.5"><ArrowRight size={16} />صفحه اصلی</a>
      <button onClick={onLogout} className="btn btn-pill bg-danger-soft !py-2.5 text-danger hover:brightness-95"><LogOut size={16} />خروج</button>
    </PageTitle>
    <div className="mb-8 grid grid-cols-2 gap-4 sm:grid-cols-3">{stats.map(([l, v, Icon, k], i) => <button key={l} onClick={() => setTab(k.slice(4))} className={`card text-right transition hover:-translate-y-0.5 hover:shadow-lift ${i === 0 ? "col-span-2 !border-0 bg-hero !text-white sm:col-span-1" : ""}`}><div className="flex items-center justify-between"><span className={`text-sm ${i === 0 ? "text-white/60" : "text-muted"}`}>{l}</span><Icon size={18} className={i === 0 ? "text-[#f7c85c]" : "text-coral"} /></div><div className="mt-3 text-2xl font-black">{v}</div></button>)}</div>
    <div className="grid gap-8 md:grid-cols-[220px_1fr]">
      <nav aria-label="بخش‌های حساب" className="-mx-5 flex gap-2 overflow-x-auto px-5 pb-1 md:sticky md:top-24 md:mx-0 md:h-fit md:flex-col md:gap-1 md:overflow-visible md:px-0">{tabs.map(([k, l, Icon]) => <button key={k} onClick={() => setTab(k)} aria-current={tab === k} className={`flex shrink-0 items-center gap-2.5 whitespace-nowrap rounded-xl px-4 py-3 text-sm font-bold transition ${tab === k ? "bg-primary text-onprimary shadow-soft" : "text-muted hover:bg-surface2 hover:text-ink"}`}><Icon size={18} />{l}{k === "notifications" && unread > 0 && <span className="mr-auto rounded-full bg-coral px-2 py-0.5 text-[10px] text-onprimary">{fa(unread)}</span>}</button>)}</nav>
      <section aria-live="polite" className="min-w-0">
        {tab === "notifications" && <Notifications coreFetch={coreFetch} notify={notify} onCount={setUnread} />}
        {tab === "orders" && <Orders orders={orders} />}
        {tab === "vpn" && <Vpn coreFetch={coreFetch} storeId={storeId} notify={notify} reload={reload} />}
        {tab === "wallet" && <Wallet coreFetch={coreFetch} storeId={storeId} wallet={wallet} reload={reload} notify={notify} />}
        {tab === "profile" && <Profile coreFetch={coreFetch} account={account} notify={notify} reload={reload} />}
        {tab === "tickets" && <Tickets coreFetch={coreFetch} storeId={storeId} notify={notify} />}
      </section>
    </div>
  </div>;
}

export function Faq() {
  const items = [["چطور سرویس را فعال کنم؟", "پس از ورود و شارژ کیف پول، سرویس را انتخاب و پرداخت کنید؛ لینک اشتراک در بخش «اکانت‌های VPN» نمایش داده می‌شود."], ["پرداخت چگونه است؟", "خرید همیشه از کیف پول انجام می‌شود. کیف پول را با کارت‌به‌کارت (همراه رسید) یا درگاه شارژ کنید."], ["تمدید یا استرداد چطور است؟", "برای تمدید یا مشکل در سفارش، از بخش تیکت‌ها با پشتیبانی در تماس باشید."], ["قوانین استفاده", "استفاده غیرقانونی یا فروش مجدد بدون همکاری رسمی مجاز نیست؛ سرویس تست محدود به یک‌بار برای هر کاربر است."]];
  return <section id="faq" className="mx-auto max-w-3xl px-5 pb-28"><div className="eyebrow text-center">سوالات</div><h2 className="mt-3 text-center text-4xl font-black">پرسش‌های پرتکرار</h2><div className="mt-10 space-y-3">{items.map(([q, a]) => <details key={q} className="card group !p-0 transition open:shadow-lift"><summary className="flex cursor-pointer items-center justify-between gap-4 p-5 font-extrabold">{q}<ChevronDown size={20} className="chev shrink-0 text-muted transition-transform" /></summary><p className="px-5 pb-5 leading-8 text-muted">{a}</p></details>)}</div></section>;
}
