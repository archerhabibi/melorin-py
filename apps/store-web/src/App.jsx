// Subject + plan: Melorin storefront for VPN customers. A warm Persian service counter meets a precise account console: dusk navy, saffron, and mint; hero catalog, store-scoped quote, wallet, and orders in one calm flow.
import { useEffect, useState } from "react";
import Dashboard, { Faq } from "./Dashboard.jsx";
import Reseller from "./Reseller.jsx";
import { clearTokens, getAccessToken, setTokens } from "./auth.js";

export default function App(){
  const [active, setActive] = useState("Orbit");
  const [notice, setNotice] = useState("");
  const [catalog, setCatalog] = useState([]);
  const [apiState, setApiState] = useState("در حال اتصال به Core");
  const [accessToken, setAccessToken] = useState(() => getAccessToken());
  const [modal, setModal] = useState("");
  const [email, setEmail] = useState("");
  const [loginCode, setLoginCode] = useState("");
  const [account, setAccount] = useState(null);
  const [wallet, setWallet] = useState(null);
  const [orders, setOrders] = useState([]);
  const [storeId, setStoreId] = useState("");
  const [ticket, setTicket] = useState("");
  const [selectedQuote, setSelectedQuote] = useState(null);
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => { const h = () => setHash(window.location.hash); window.addEventListener("hashchange", h); return () => window.removeEventListener("hashchange", h); }, []);
  const notify = (m) => { setNotice(m); setTimeout(() => setNotice(""), 2500); };
  const logout = () => { clearTokens(); setAccessToken(""); setAccount(null); setWallet(null); setOrders([]); window.location.hash = ""; };
  const onDash = hash === "#/dashboard" && accessToken;
  const base = (import.meta.env?.VITE_MELORIN_API_URL || window.location.origin).replace(/\/$/, "");
  async function coreFetch(path, options={}) {
    let token = accessToken;
    let response = await fetch(`${base}${path}`, {...options, credentials:"include", headers: {...(options.headers||{}), ...(token ? {Authorization:`Bearer ${token}`} : {})}});
    if (response.status === 401) {
      {
        const rr = await fetch(`${base}/api/v1/auth/refresh`, {method:"POST", credentials:"include", headers:{"Content-Type":"application/json"}, body:"{}"});
        if (rr.ok) { const pair = await rr.json(); setTokens(pair); setAccessToken(pair.access_token); response = await fetch(`${base}${path}`, {...options, headers: {...(options.headers||{}), Authorization:`Bearer ${pair.access_token}`}}); }
      }
    }
    return response;
  }
  async function loadAccount() {
    if (!accessToken || !storeId) return;
    try {
      const [me, w, os] = await Promise.all([
        coreFetch("/api/v1/me").then(r => r.json()),
        coreFetch(`/api/v1/stores/${storeId}/wallet`).then(r => r.json()),
        coreFetch(`/api/v1/stores/${storeId}/orders`).then(r => r.json()),
      ]);
      setAccount(me); setWallet(w); setOrders(Array.isArray(os) ? os : os.items || []);
    } catch { setNotice("ورود را کامل کنید تا حساب نمایش داده شود"); }
  }
  async function requestCode() {
    const r = await fetch(`${base}/api/v1/auth/email/request-code`, {method:"POST", credentials:"include", headers:{"Content-Type":"application/json"}, body:JSON.stringify({email})});
    if (!r.ok) throw Error("login request failed");
    setModal("code"); setNotice("کد ورود ارسال شد");
  }
  async function verifyCode() {
    const r = await fetch(`${base}/api/v1/auth/email/verify-code`, {method:"POST", credentials:"include", headers:{"Content-Type":"application/json"}, body:JSON.stringify({email, code:loginCode})});
    if (!r.ok) throw Error("invalid code");
    const pair = await r.json(); setTokens(pair); setAccessToken(pair.access_token); setModal(""); setNotice("خوش آمدی");
  }
  async function buySelected() {
    const r = await coreFetch(`/api/v1/stores/${storeId}/orders`, {method:"POST", headers:{"Content-Type":"application/json","Idempotency-Key":`web-${crypto.randomUUID()}`}, body:JSON.stringify({product_id:selectedQuote?.product_id || selectedQuote?.id, payment_method:"wallet", kind:"purchase"})});
    if (!r.ok) throw Error("order failed");
    setModal(""); setNotice("سفارش ثبت شد"); loadAccount();
  }
  useEffect(() => {
    const base = (import.meta.env?.VITE_MELORIN_API_URL || window.location.origin).replace(/\/$/, "");
    coreFetch(`/api/v1/stores/main`, {headers: {Accept: "application/json"}})
      .then(r => r.ok ? r.json() : Promise.reject(new Error(String(r.status))))
      .then(store => { setStoreId(store.id); return fetch(`${base}/api/v1/stores/${store.id}/catalog`, {headers: {Accept: "application/json"}}); })
      .then(r => r.ok ? r.json() : Promise.reject(new Error(String(r.status))))
      .then(data => { setCatalog(Array.isArray(data) ? data : (data.items || [])); setApiState("اتصال Core برقرار است"); })
      .catch(() => { setCatalog([]); setApiState("Core در دسترس نیست؛ کاتالوگ موقتاً نمایش داده نمی‌شود"); });
  }, []);
  useEffect(() => {
    if (accessToken) return;
    fetch(`${base}/api/v1/auth/refresh`, {method:"POST", credentials:"include", headers:{"Content-Type":"application/json"}, body:"{}"})
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(pair => { setTokens(pair); setAccessToken(pair.access_token); })
      .catch(() => {});
  }, []);
  useEffect(() => { if (storeId && accessToken) loadAccount(); }, [storeId, accessToken]);
  const choose = async (product) => {
    const name = product.name || product.title || product.code;
    setActive(name);
    if (!accessToken) { setModal("login"); setNotice("برای خرید وارد شوید"); return; }
    try {
      const r = await coreFetch(`/api/v1/stores/${storeId}/checkout/quote`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({product_id: product.product_id || product.id})});
      const q = await r.json(); setSelectedQuote(q); setModal("checkout");
    } catch { setNotice("پیش‌فاکتور از Core دریافت نشد"); }
  };
  return <div className="min-h-screen bg-[#f4f1e8] text-[#10233f]" dir="rtl">
    <style>{`:root{font-family:Tahoma,Arial,sans-serif} .latin{font-family:Arial,sans-serif} .grain{background-image:radial-gradient(rgba(16,35,63,.07) .7px,transparent .7px);background-size:7px 7px}
      .float{animation:float 5s ease-in-out infinite}@keyframes float{50%{transform:translateY(-8px)}}`}</style>
    <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-6">
      <div className="flex items-center gap-3"><div className="grid h-10 w-10 place-items-center rounded-2xl bg-[#10233f] text-[#f7c85c] text-xl font-bold">م</div><div><div className="text-lg font-extrabold">ملورین</div><div className="latin text-[10px] tracking-[.2em] text-[#6d7b87]">MELORIN / MAIN STORE</div></div></div>
      <nav className="hidden items-center gap-8 text-sm font-medium md:flex"><a href="#plans">سرویس‌ها</a><a href="#why">چرا ملورین؟</a><a href="#faq">سوالات</a><a href="#/dashboard">حساب من</a></nav>
      <button onClick={()=>accessToken?(window.location.hash="#/dashboard"):setModal("login")} className="rounded-full border border-[#cfd3cc] px-4 py-2 text-sm font-semibold">{account?.display_name || "ورود / ثبت‌نام"}</button>
    </header>
    <main>
      {hash === "#/reseller" && accessToken ? <Reseller coreFetch={coreFetch} notify={notify}/> : onDash ? <Dashboard coreFetch={coreFetch} storeId={storeId} account={account} wallet={wallet} orders={orders} reload={loadAccount} notify={notify} onLogout={logout}/> : <>
      <section className="mx-auto grid max-w-6xl gap-10 px-6 pb-20 pt-8 md:grid-cols-[1.1fr_.9fr] md:items-center">
        <div><div className="mb-6 inline-flex items-center gap-2 rounded-full bg-[#dcefe4] px-4 py-2 text-xs font-bold text-[#17634c]"><span className="h-2 w-2 rounded-full bg-[#32a97b]"/> شبکه پایدار، بدون پیچیدگی</div><h1 className="max-w-xl text-5xl font-extrabold leading-[1.12] tracking-tight md:text-7xl">اینترنتت را<br/><span className="text-[#db7b54]">آزادتر</span> انتخاب کن.</h1><p className="mt-7 max-w-lg text-lg leading-9 text-[#536170]">سرویس VPN ساده، سریع و قابل تمدید. قیمت‌گذاری شفاف، کیف پول امن و پشتیبانی واقعی، همه در یک جا.</p><div className="mt-9 flex flex-wrap gap-3"><a href="#plans" className="rounded-full bg-[#10233f] px-7 py-4 text-sm font-bold text-white shadow-lg shadow-[#10233f]/15">دیدن سرویس‌ها</a><button onClick={()=>document.getElementById("faq")?.scrollIntoView({behavior:"smooth"})} className="rounded-full bg-white px-7 py-4 text-sm font-bold ring-1 ring-[#d7d8d1]">چطور کار می‌کند؟</button></div></div>
        <div className="relative"><div className="grain float relative mx-auto max-w-md overflow-hidden rounded-[2rem] bg-[#10233f] p-7 text-white shadow-2xl shadow-[#10233f]/20"><div className="absolute -left-12 -top-16 h-48 w-48 rounded-full bg-[#f7c85c] blur-2xl opacity-80"/><div className="relative flex items-start justify-between"><span className="rounded-full bg-white/10 px-3 py-1 text-xs">ملورین</span><span className="latin text-xs tracking-widest text-[#f7c85c]">MELORIN</span></div><div className="relative mt-20"><div className="text-sm text-white/60">سرویس VPN</div><div className="mt-2 text-3xl font-bold">خرید ساده، تحویل خودکار</div><div className="mt-7 flex items-end justify-between"><div><div className="text-xs text-white/50">فعال‌سازی</div><div className="mt-1 text-lg font-semibold">پس از پرداخت</div></div><div className="text-left"><div className="text-xs text-white/50">پرداخت</div><div className="mt-1 text-lg font-semibold text-[#8ce0ba]">کیف پول</div></div></div></div></div><div className="absolute -bottom-5 -right-5 rounded-2xl bg-[#f7c85c] px-5 py-4 text-sm font-extrabold text-[#10233f] shadow-xl">تحویل خودکار ✓</div></div>
      </section>
      <section id="plans" className="bg-[#10233f] px-6 py-20 text-white"><div className="mx-auto max-w-6xl"><div className="flex flex-col justify-between gap-5 md:flex-row md:items-end"><div><div className="text-sm font-bold text-[#f7c85c]">سرویس‌ها</div><h2 className="mt-3 text-4xl font-extrabold">برای ریتم خودت انتخاب کن.</h2></div><p className="max-w-sm leading-7 text-white/60">{apiState} · قیمت نهایی فقط از Core می‌آید.</p></div><div className="mt-10 grid gap-4 md:grid-cols-3">{catalog.length ? catalog.map(p=>{const name=p.name || p.title || p.code || "Melorin"; return <button key={String(p.id||name)} onClick={()=>choose(p)} className={`group text-right rounded-[1.5rem] p-6 transition hover:-translate-y-1 ${active===name?'bg-[#f7c85c] text-[#10233f]':'bg-white/10 text-white hover:bg-white/15'}`}><div className="flex items-center justify-between"><span className="text-2xl font-extrabold">{name}</span><span className="h-4 w-4 rounded-full bg-[#8ce0ba]"/></div><div className={`mt-8 text-sm ${active===name?'text-[#40516a]':'text-white/60'}`}>{p.meta || `${p.duration_days || "?"} روز · ${p.traffic_gb || "?"} GB`}</div><div className="mt-5 flex items-baseline gap-2"><span className="text-3xl font-extrabold">{p.price ? new Intl.NumberFormat("fa-IR").format(p.price) : (p.display_price || "قیمت در Core")}</span><span className="text-xs opacity-60">تومان</span></div><div className={`mt-6 text-sm font-bold ${active===name?'text-[#10233f]':'text-[#f7c85c]'}`}>{active===name?'انتخاب شده ✓':'مشاهده پیش‌فاکتور ←'}</div></button>}) : <div className="rounded-3xl border border-white/15 bg-white/5 p-8 text-center text-white/70">کاتالوگ موقتاً در دسترس نیست. لطفاً بعداً دوباره تلاش کنید.</div>}</div></div></section>
      <section id="why" className="mx-auto max-w-6xl px-6 py-20"><div className="grid gap-8 md:grid-cols-3"><div><div className="text-sm font-bold text-[#db7b54]">چرا ملورین؟</div><h2 className="mt-3 text-4xl font-extrabold leading-tight">کمتر تنظیم کن.<br/>بیشتر وصل باش.</h2></div>{[['۰۱','کیف پول شفاف','شارژ، خرید و تمدید را در یک گردش مالی ساده ببین.'],['۰۲','پشتیبانی انسانی','اگر جایی گیر کردی، آدم واقعی پشت خط است.'],['۰۳','بدون قفل شدن','سرویس و اطلاعاتت مال خودت است، نه یک پنل مبهم.']].map(([n,t,d])=><div key={n} className="rounded-3xl border border-[#d9ddd4] bg-white/50 p-6"><div className="latin text-sm font-bold text-[#db7b54]">{n}</div><h3 className="mt-10 text-xl font-extrabold">{t}</h3><p className="mt-3 leading-7 text-[#687582]">{d}</p></div>)}</div></section>
      <section id="account" className="mx-6 mb-12 overflow-hidden rounded-[2rem] bg-[#dcefe4] px-7 py-10 md:mx-auto md:max-w-6xl md:px-14"><div className="flex flex-col justify-between gap-8 md:flex-row md:items-center"><div><div className="text-sm font-bold text-[#17634c]">حساب من</div><h2 className="mt-3 text-3xl font-extrabold">سرویس، کیف پول، سفارش‌ها.</h2><p className="mt-3 text-[#536170]">{wallet ? `موجودی کیف پول: ${new Intl.NumberFormat("fa-IR").format(wallet.balance)} ${wallet.currency} · ${orders.length} سفارش` : "همه‌چیز آماده است تا از همان جایی که بودی ادامه بدهی."}</p></div><button onClick={()=>accessToken?(window.location.hash="#/dashboard"):setModal("login")} className="rounded-full bg-[#10233f] px-7 py-4 text-sm font-bold text-white">ورود به حساب ←</button></div></section>
      <Faq/>
      </>}
    </main>
    <footer className="mx-auto flex max-w-6xl flex-col gap-3 px-6 pb-8 text-sm text-[#73808b] md:flex-row md:justify-between"><span>© ۲۰۲۶ ملورین</span><span>امن، روشن، بدون حاشیه.</span></footer>
    {modal&&<div className="fixed inset-0 z-50 grid place-items-center bg-[#10233f]/60 p-4" onClick={()=>setModal("")}><div className="w-full max-w-md rounded-3xl bg-[#fdfcf8] p-7 shadow-2xl" onClick={e=>e.stopPropagation()}>
      {modal==="login"&&<><h3 className="text-2xl font-extrabold">ورود امن</h3><p className="mt-2 text-sm text-[#687582]">کد ورود به ایمیل شما ارسال می‌شود.</p><input value={email} onChange={e=>setEmail(e.target.value)} className="mt-5 w-full rounded-xl border p-3" placeholder="email@example.com"/><button onClick={()=>requestCode().catch(()=>setNotice("ارسال کد ناموفق بود"))} className="mt-4 w-full rounded-xl bg-[#10233f] p-3 font-bold text-white">ارسال کد</button></>}
      {modal==="code"&&<><h3 className="text-2xl font-extrabold">کد ورود</h3><input value={loginCode} onChange={e=>setLoginCode(e.target.value)} className="mt-5 w-full rounded-xl border p-3 text-center tracking-[.4em]" placeholder="کد ورود"/><button onClick={()=>verifyCode().catch(()=>setNotice("کد نامعتبر است"))} className="mt-4 w-full rounded-xl bg-[#10233f] p-3 font-bold text-white">تأیید</button></>}
      {modal==="checkout"&&<><h3 className="text-2xl font-extrabold">پیش‌فاکتور {active}</h3><div className="mt-5 rounded-2xl bg-[#dcefe4] p-4">مبلغ نهایی: <b>{new Intl.NumberFormat("fa-IR").format(selectedQuote?.total||0)} {selectedQuote?.currency}</b><br/>موجودی: {new Intl.NumberFormat("fa-IR").format(selectedQuote?.wallet_balance||0)}</div><button disabled={!selectedQuote?.sufficient_funds} onClick={()=>buySelected().catch(()=>setNotice("ثبت سفارش ناموفق بود"))} className="mt-4 w-full rounded-xl bg-[#10233f] p-3 font-bold text-white disabled:opacity-40">پرداخت از کیف پول و ثبت سفارش</button></>}
      {modal==="account"&&<><h3 className="text-2xl font-extrabold">حساب من</h3><div className="mt-5 rounded-2xl bg-[#dcefe4] p-4">موجودی: {new Intl.NumberFormat("fa-IR").format(wallet?.balance||0)} {wallet?.currency}</div><p className="mt-4 text-sm">سفارش‌ها: {orders.length}</p></>}
    </div></div>}
    {notice&&<div className="fixed bottom-6 left-1/2 -translate-x-1/2 rounded-full bg-[#10233f] px-5 py-3 text-sm font-semibold text-white shadow-xl">{notice}</div>}
  </div>
}
