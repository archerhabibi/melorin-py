import { useEffect, useState } from "react";
import { Bell, ChevronDown, Copy, Gauge, KeyRound, LifeBuoy, LogOut, Package, Store, Wallet as WalletIcon, ArrowRight, Link2 } from "lucide-react";
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

function Vpn({ coreFetch, notify }) {
  const [rows, setRows] = useState(null);
  useEffect(() => { coreFetch("/api/v1/vpn-accounts").then((r) => r.json()).then(setRows).catch(() => setRows([])); }, []);
  if (!rows) return <Loading rows={2} />;
  if (!rows.length) return <Empty icon={Gauge} text="اکانتی ندارید. از بخش سرویس‌ها خرید کنید."><a href="#plans" className="btn-primary mt-5">دیدن سرویس‌ها</a></Empty>;
  const copy = (t) => navigator.clipboard?.writeText(t).then(() => notify("کپی شد"));
  return <div className="grid gap-4 md:grid-cols-2">{rows.map((a) => {
    const pct = a.traffic_limit_bytes ? Math.min(100, (a.traffic_used_bytes / a.traffic_limit_bytes) * 100) : 0;
    return <div key={a.id} className={card}>
      <div className="flex items-center justify-between"><b className="latin">{a.username}</b><StatusBadge status={a.status} /></div>
      <div className="mt-4 text-xs text-muted">انقضا: {fd(a.expires_at)}</div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-surface2"><div className={`h-full rounded-full ${pct > 85 ? "bg-danger" : "bg-coral"}`} style={{ width: `${pct}%` }} /></div>
      <div className="mt-1 text-xs text-muted">{gb(a.traffic_used_bytes)} از {a.traffic_limit_bytes ? gb(a.traffic_limit_bytes) : "∞"} گیگ</div>
      {a.subscription_url && <button onClick={() => copy(a.subscription_url)} className="btn-primary mt-4 w-full"><Copy size={16} />کپی لینک اشتراک</button>}
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
    } catch { notify("ایجاد درخواست شارژ ناموفق بود"); } finally { setBusy(false); }
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

function Tickets({ coreFetch, storeId, notify }) {
  const [list, setList] = useState([]);
  const [sel, setSel] = useState(null);
  const [msgs, setMsgs] = useState([]);
  const [form, setForm] = useState({ subject: "", body: "" });
  const [reply, setReply] = useState("");
  const load = () => coreFetch(`/api/v1/stores/${storeId}/tickets`).then((r) => r.json()).then(setList).catch(() => {});
  useEffect(() => { load(); }, [storeId]);
  const open = (t) => { setSel(t); coreFetch(`/api/v1/tickets/${t.id}/messages`).then((r) => r.json()).then(setMsgs); };
  async function create() {
    const r = await coreFetch(`/api/v1/stores/${storeId}/tickets`, { method: "POST", headers: J, body: JSON.stringify(form) });
    if (r.ok) { setForm({ subject: "", body: "" }); notify("تیکت ثبت شد"); load(); } else notify("ثبت تیکت ناموفق بود");
  }
  async function send() {
    const r = await coreFetch(`/api/v1/tickets/${sel.id}/messages`, { method: "POST", headers: J, body: JSON.stringify({ body: reply }) });
    if (r.ok) { setReply(""); open(sel); }
  }
  if (sel) return <div className={card}><button onClick={() => setSel(null)} className="text-sm font-bold text-coral">→ بازگشت</button><h4 className="mt-2 font-extrabold">{sel.subject}</h4>
    <div className="mt-4 space-y-3">{msgs.map((m) => <div key={m.id} className={`max-w-[85%] rounded-2xl p-3 text-sm leading-7 ${m.is_staff ? "bg-mint-soft" : "mr-auto bg-surface2"}`}>{m.body}<div className="mt-1 text-[10px] text-muted">{m.is_staff ? "پشتیبانی" : "شما"} · {fd(m.created_at)}</div></div>)}</div>
    <div className="mt-4 flex gap-2"><input className={inp} value={reply} onChange={(e) => setReply(e.target.value)} placeholder="پیام…" /><button disabled={!reply.trim()} onClick={send} className={btn}>ارسال</button></div></div>;
  return <div className="grid gap-5 md:grid-cols-2">
    <div className={card}><h4 className="font-extrabold">تیکت جدید</h4><input className={`${inp} mt-3`} placeholder="موضوع" value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} /><textarea rows={4} className={`${inp} mt-3`} placeholder="توضیحات" value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} /><button disabled={form.subject.length < 2 || !form.body} onClick={create} className={`${btn} mt-3 w-full`}>ثبت تیکت</button></div>
    <div className="space-y-3">{list.length ? list.map((t) => <button key={t.id} onClick={() => open(t)} className={`${card} flex w-full items-center justify-between text-right`}><div><b>{t.subject}</b><div className="mt-1 text-xs text-muted">{fd(t.updated_at)}</div></div><StatusBadge status={t.status} /></button>) : <Empty text="تیکتی ندارید." />}</div>
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
  async function setPass() { const r = await post("/api/v1/me/password", { password: pw }); notify(r.ok ? "رمز عبور تنظیم شد" : "رمز نامعتبر است (حداقل ۸ کاراکتر)"); r.ok && setPw(""); }
  async function setup2fa() { const r = await post("/api/v1/me/2fa/setup"); r.ok ? setTotp(await r.json()) : notify("راه‌اندازی ناموفق بود"); }
  async function enable2fa() { const r = await post("/api/v1/me/2fa/enable", { code }); if (r.ok) { notify("۲FA فعال شد"); setTotp(null); setCode(""); reload(); } else notify("کد نادرست است"); }
  return <div className="grid gap-5 md:grid-cols-2">
    <div className={card}><h4 className="font-extrabold">پروفایل</h4><div className="mt-2 text-xs text-muted">{account?.email || "ایمیل ثبت نشده"}</div><input className={`${inp} mt-3`} value={name} onChange={(e) => setName(e.target.value)} placeholder="نام نمایشی" /><button onClick={saveName} className={`${btn} mt-3`}>ذخیره</button></div>
    <div className={card}><h4 className="font-extrabold">دعوت دوستان (رفرال)</h4><p className="mt-2 text-sm text-muted">کد دعوت شما:</p><div className="mt-2 flex gap-2"><code className="latin flex-1 rounded-xl bg-surface2 p-3 text-center font-bold">{account?.referral_code || "—"}</code><button onClick={() => copy(account?.referral_code)} className={btn}>کپی</button></div></div>
    <div className={card}><h4 className="font-extrabold">اتصال تلگرام</h4>{link ? <div className="mt-3 text-sm leading-7">کد: <b className="latin">{link.code}</b> (تا {Math.round(link.expires_in / 60)} دقیقه معتبر){link.telegram_deeplink && <a href={link.telegram_deeplink} target="_blank" rel="noreferrer" className={`${btn} mt-3 block text-center`}>باز کردن در تلگرام</a>}</div> : <button onClick={tg} className={`${btn} mt-3`}>ساخت کد اتصال</button>}</div>
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
        {tab === "vpn" && <Vpn coreFetch={coreFetch} notify={notify} />}
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
