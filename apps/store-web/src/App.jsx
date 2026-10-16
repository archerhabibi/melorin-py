// Subject + plan: Melorin storefront for VPN customers. A warm Persian service counter meets a precise account console: dusk navy, saffron, and mint; hero catalog, store-scoped quote, wallet, and orders in one calm flow.
// Design system v2: tokens live in styles.css (light + dark), shared primitives in ui.jsx.
import { useEffect, useState } from "react";
import { ArrowLeft, Check, CreditCard, Home, KeyRound, LayoutGrid, LifeBuoy, Link2, Loader2, Lock, Mail, Menu, RefreshCw, ShieldCheck, Sparkles, User, Wallet as WalletIcon, X, Zap } from "lucide-react";
import Dashboard, { Faq } from "./Dashboard.jsx";
import Reseller from "./Reseller.jsx";
import { clearTokens, getAccessToken, setTokens } from "./auth.js";
import { Modal, ThemeToggle, Toast, fa } from "./ui.jsx";

const NAV = [["#plans", "سرویس‌ها"], ["#how", "نحوه خرید"], ["#why", "چرا ملورین؟"], ["#faq", "سوالات"]];
const STEPS = [
  [Mail, "ورود با ایمیل", "بدون رمز عبور؛ کد ورود به ایمیلت می‌آید."],
  [WalletIcon, "شارژ کیف پول", "کارت‌به‌کارت با رسید یا درگاه آنلاین."],
  [LayoutGrid, "انتخاب سرویس", "پیش‌فاکتور شفاف را ببین و پرداخت کن."],
  [Link2, "دریافت لینک", "لینک اشتراک بلافاصله در حسابت آماده است."],
];
const NAME_RE = /^[A-Za-z0-9_-]{3,}$/;
async function errOf(r, fallback) { try { const d = await r.json(); return d?.error?.message || (typeof d?.detail === "string" ? d.detail : "") || fallback; } catch { return fallback; } }
const WHY = [
  [WalletIcon, "کیف پول شفاف", "شارژ، خرید و تمدید را در یک گردش مالی ساده ببین؛ هر تراکنش ردیف مشخصی دارد."],
  [LifeBuoy, "پشتیبانی انسانی", "اگر جایی گیر کردی، از بخش تیکت‌ها پیام بده و پاسخ همان‌جا بیاید."],
  [ShieldCheck, "امنیت حساب", "ورود با کد ایمیل، امکان ورود دومرحله‌ای و مدیریت رمز عبور."],
  [KeyRound, "بدون قفل شدن", "سرویس و اطلاعاتت مال خودت است، نه یک پنل مبهم."],
];

function Logo() {
  return <a href="#" className="flex items-center gap-3" aria-label="ملورین؛ صفحه اصلی">
    <span className="grid h-10 w-10 place-items-center rounded-2xl bg-hero text-xl font-extrabold text-[#f7c85c] shadow-soft">م</span>
    <span className="leading-tight"><span className="block text-lg font-extrabold">ملورین</span><span className="latin block text-[10px] font-semibold tracking-[.22em] text-muted">MELORIN</span></span>
  </a>;
}

function HeroVisual() {
  return <div className="relative mx-auto w-full max-w-sm" aria-hidden="true">
    <div className="absolute -inset-6 rounded-full bg-accent/30 blur-3xl" />
    <div className="anim-float relative overflow-hidden rounded-4xl bg-hero p-6 shadow-lift">
      <div className="absolute -left-10 -top-14 h-44 w-44 rounded-full bg-[#f7c85c] opacity-70 blur-3xl" />
      <div className="relative flex items-center justify-between text-xs"><span className="rounded-full bg-white/10 px-3 py-1">سرویس شما</span><span className="latin tracking-widest text-[#f7c85c]">MELORIN</span></div>
      <div className="relative mt-10 grid place-items-center">
        <span className="absolute h-36 w-36 animate-ping rounded-full bg-[#86e0b8]/15" />
        <span className="absolute h-28 w-28 rounded-full border border-[#86e0b8]/30" />
        <span className="relative grid h-20 w-20 place-items-center rounded-full bg-[#86e0b8] text-[#0c1b33] shadow-[0_0_40px_#86e0b855]"><ShieldCheck size={36} strokeWidth={2} /></span>
      </div>
      <div className="relative mt-9 text-center"><div className="text-xl font-extrabold">متصل و امن</div><div className="mt-1 text-xs text-white/55">یک لینک اشتراک، همه دستگاه‌ها</div></div>
      <div className="relative mt-7 grid grid-cols-2 gap-3 text-xs">
        <div className="rounded-2xl bg-white/[.07] p-3"><div className="text-white/50">فعال‌سازی</div><div className="mt-1 font-bold">پس از پرداخت</div></div>
        <div className="rounded-2xl bg-white/[.07] p-3"><div className="text-white/50">پرداخت</div><div className="mt-1 font-bold text-[#86e0b8]">کیف پول</div></div>
      </div>
    </div>
    <div className="absolute -bottom-4 -right-3 flex items-center gap-2 rounded-2xl bg-[#f7c85c] px-4 py-3 text-sm font-extrabold text-[#10233f] shadow-lift"><Zap size={16} /> تحویل خودکار</div>
  </div>;
}

export default function App(){
  const [active, setActive] = useState("Orbit");
  const [notice, setNotice] = useState("");
  const [catalog, setCatalog] = useState([]);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [pools, setPools] = useState([]);
  const [poolId, setPoolId] = useState("");
  const [panelId, setPanelId] = useState("");
  const [accountName, setAccountName] = useState("");
  const [pkgLoading, setPkgLoading] = useState(false);
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
  const [menu, setMenu] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  useEffect(() => { const h = () => { setHash(window.location.hash); setMenu(false); }; window.addEventListener("hashchange", h); return () => window.removeEventListener("hashchange", h); }, []);
  const notify = (m) => { setNotice(m); setTimeout(() => setNotice(""), 2800); };
  const logout = () => { clearTokens(); setAccessToken(""); setAccount(null); setWallet(null); setOrders([]); window.location.hash = ""; };
  const onDash = hash === "#/dashboard" && accessToken;
  const onReseller = hash === "#/reseller" && accessToken;
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
  const pool = pools.find((x) => x.id === poolId);
  const manual = pool?.selection_mode === "manual";
  const customName = pool?.naming_mode === "custom";
  const panelLabel = pool?.panels?.find((x) => x.id === panelId)?.label;
  const poolBody = () => ({ panel_group_id: poolId, ...(manual ? { selected_panel_id: panelId } : {}) });
  async function buySelected() {
    const r = await coreFetch(`/api/v1/stores/${storeId}/orders`, {method:"POST", headers:{"Content-Type":"application/json","Idempotency-Key":`web-${crypto.randomUUID()}`}, body:JSON.stringify({product_id:selectedQuote?.product_id || selectedQuote?.id, payment_method:"wallet", kind:"purchase", ...poolBody(), ...(customName ? { account_name: accountName.trim() } : {})})});
    if (!r.ok) throw Error(await errOf(r, "order failed"));
    setModal(""); setNotice("سفارش ثبت شد"); loadAccount();
  }
  const run = async (fn, failMsg) => { setBusy(true); try { await fn(); } catch (e) { setNotice(e?.message && !/^(order failed|login request failed|invalid code)$/.test(e.message) ? e.message : failMsg); } finally { setBusy(false); } };
  useEffect(() => {
    const base = (import.meta.env?.VITE_MELORIN_API_URL || window.location.origin).replace(/\/$/, "");
    setCatalogLoading(true);
    // A reseller's own domain shows that reseller's store; any other host (main domain, localhost) shows the main store.
    coreFetch(`/api/v1/stores/by-domain/${encodeURIComponent(window.location.hostname.toLowerCase())}`, {headers: {Accept: "application/json"}})
      .then(r => r.ok ? r : coreFetch(`/api/v1/stores/main`, {headers: {Accept: "application/json"}}))
      .then(r => r.ok ? r.json() : Promise.reject(new Error(String(r.status))))
      .then(store => { setStoreId(store.id); return fetch(`${base}/api/v1/stores/${store.id}/pools`, {headers: {Accept: "application/json"}}); })
      .then(r => r.ok ? r.json() : Promise.reject(new Error(String(r.status))))
      .then(data => { const list = Array.isArray(data) ? data : (data.items || []); setPools(list); setPoolId((cur) => list.some((x) => x.id === cur) ? cur : (list.length === 1 ? list[0].id : "")); setApiState("اتصال Core برقرار است"); })
      .catch(() => { setPools([]); setApiState("Core در دسترس نیست؛ سرویس‌ها موقتاً نمایش داده نمی‌شود"); })
      .finally(() => setCatalogLoading(false));
  }, [reloadKey]);
  useEffect(() => {
    setCatalog([]);
    if (!storeId || !poolId) return;
    const base = (import.meta.env?.VITE_MELORIN_API_URL || window.location.origin).replace(/\/$/, "");
    let live = true;
    setPkgLoading(true);
    fetch(`${base}/api/v1/stores/${storeId}/pools/${poolId}/packages`, {headers: {Accept: "application/json"}})
      .then(r => r.ok ? r.json() : Promise.reject(new Error(String(r.status))))
      .then(data => live && setCatalog(Array.isArray(data) ? data : (data.items || [])))
      .catch(() => live && setCatalog([]))
      .finally(() => live && setPkgLoading(false));
    return () => { live = false; };
  }, [storeId, poolId, reloadKey]);
  useEffect(() => {
    if (accessToken) return;
    fetch(`${base}/api/v1/auth/refresh`, {method:"POST", credentials:"include", headers:{"Content-Type":"application/json"}, body:"{}"})
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(pair => { setTokens(pair); setAccessToken(pair.access_token); })
      .catch(() => {});
  }, []);
  useEffect(() => { if (storeId && accessToken) loadAccount(); }, [storeId, accessToken]);
  const pickPool = (id) => { setPoolId(id); setPanelId(""); setSelectedQuote(null); setActive(""); };
  const choose = async (product) => {
    const name = product.name || product.title || product.code;
    setActive(name);
    if (!accessToken) { setModal("login"); setNotice("برای خرید وارد شوید"); return; }
    if (!poolId || (manual && !panelId)) { setNotice("ابتدا استخر فروش و گزینه را انتخاب کنید"); return; }
    if (customName && !NAME_RE.test(accountName.trim())) { setNotice("نام کاربری حداقل ۳ کاراکتر و فقط شامل حروف انگلیسی، عدد، _ و - باشد"); return; }
    try {
      const r = await coreFetch(`/api/v1/stores/${storeId}/checkout/quote`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({product_id: product.product_id || product.id, ...poolBody()})});
      if (!r.ok) { setNotice(await errOf(r, "پیش‌فاکتور از Core دریافت نشد")); return; }
      const q = await r.json(); setSelectedQuote({ product_id: product.product_id || product.id, ...q }); setModal("checkout");
    } catch { setNotice("پیش‌فاکتور از Core دریافت نشد"); }
  };
  const goAccount = () => accessToken ? (window.location.hash = "#/dashboard") : setModal("login");
  const validEmail = /^\S+@\S+\.\S+$/.test(email.trim());
  const inApp = onDash || onReseller;

  return <div className="min-h-screen" dir="rtl">
    <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:right-4 focus:top-4 focus:z-[70] focus:rounded-xl focus:bg-surface focus:px-4 focus:py-2">پرش به محتوا</a>
    <header className="glass sticky top-0 z-40 border-b border-line/70">
      <div className="mx-auto flex h-[68px] max-w-6xl items-center justify-between gap-4 px-5">
        <Logo />
        <nav className="hidden items-center gap-1 text-sm font-semibold md:flex" aria-label="ناوبری اصلی">{NAV.map(([h, l]) => <a key={h} href={inApp ? `#${h.slice(1)}` : h} className="rounded-full px-4 py-2 text-muted transition hover:bg-surface2 hover:text-ink">{l}</a>)}</nav>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <button onClick={goAccount} className="btn-primary btn-pill hidden !py-2.5 sm:inline-flex"><User size={16} />{account?.display_name || (accessToken ? "حساب من" : "ورود / ثبت‌نام")}</button>
          <button onClick={() => setMenu(!menu)} aria-label="منو" aria-expanded={menu} className="grid h-10 w-10 place-items-center rounded-full ring-1 ring-line md:hidden">{menu ? <X size={18} /> : <Menu size={18} />}</button>
        </div>
      </div>
      {menu && <div className="anim-pop border-t border-line px-5 pb-5 pt-3 md:hidden"><nav className="grid gap-1 text-sm font-bold">{NAV.map(([h, l]) => <a key={h} href={h} onClick={() => setMenu(false)} className="rounded-xl px-3 py-3 hover:bg-surface2">{l}</a>)}<button onClick={() => { setMenu(false); goAccount(); }} className="btn-primary mt-2"><User size={16} />{accessToken ? "حساب من" : "ورود / ثبت‌نام"}</button></nav></div>}
    </header>

    <main id="main" className="pb-24 md:pb-0">
      {onReseller ? <Reseller coreFetch={coreFetch} notify={notify}/> : onDash ? <Dashboard coreFetch={coreFetch} storeId={storeId} account={account} wallet={wallet} orders={orders} reload={loadAccount} notify={notify} onLogout={logout}/> : <>
      <section className="hero-bg relative overflow-hidden">
        <div className="grid-dots absolute inset-0" />
        <div className="relative mx-auto grid max-w-6xl gap-14 px-5 pb-24 pt-14 md:grid-cols-[1.1fr_.9fr] md:items-center md:pt-20">
          <div className="anim-rise">
            <div className="inline-flex items-center gap-2 rounded-full bg-mint-soft px-4 py-2 text-xs font-extrabold text-mint"><span className="relative flex h-2 w-2"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-mint opacity-60" /><span className="relative inline-flex h-2 w-2 rounded-full bg-mint" /></span>شبکه پایدار، بدون پیچیدگی</div>
            <h1 className="mt-6 text-[2.6rem] font-black leading-[1.18] tracking-tight sm:text-6xl md:text-7xl">اینترنتت را <span className="relative whitespace-nowrap text-coral">آزادتر<svg aria-hidden="true" viewBox="0 0 220 12" className="absolute -bottom-2 right-0 h-3 w-full text-accent" preserveAspectRatio="none"><path d="M2 8c40-7 90-7 216-1" fill="none" stroke="currentColor" strokeWidth="5" strokeLinecap="round"/></svg></span><br />انتخاب کن.</h1>
            <p className="mt-7 max-w-lg text-lg leading-9 text-muted">سرویس VPN ساده، سریع و قابل تمدید. قیمت‌گذاری شفاف، کیف پول امن و پشتیبانی واقعی، همه در یک جا.</p>
            <div className="mt-9 flex flex-wrap gap-3"><a href="#plans" className="btn-primary btn-pill !px-8 !py-4">دیدن سرویس‌ها <ArrowLeft size={18} /></a><a href="#how" className="btn-soft btn-pill !px-8 !py-4">چطور کار می‌کند؟</a></div>
            <ul className="mt-10 flex flex-wrap gap-x-7 gap-y-3 text-sm font-semibold text-muted">{["تحویل خودکار", "پرداخت با کیف پول", "پشتیبانی تیکتی"].map(t => <li key={t} className="flex items-center gap-2"><span className="grid h-5 w-5 place-items-center rounded-full bg-mint-soft text-mint"><Check size={13} strokeWidth={3} /></span>{t}</li>)}</ul>
          </div>
          <div className="anim-rise [animation-delay:.15s]"><HeroVisual /></div>
        </div>
      </section>

      <section id="plans" className="bg-hero px-5 py-24"><div className="mx-auto max-w-6xl">
        <div className="flex flex-col justify-between gap-5 md:flex-row md:items-end"><div><div className="text-sm font-extrabold text-[#f7c85c]">سرویس‌ها</div><h2 className="mt-3 text-4xl font-black leading-tight">برای ریتم خودت انتخاب کن.</h2></div><p className="flex max-w-sm items-center gap-2 text-sm leading-7 text-white/60"><span className={`h-2 w-2 shrink-0 rounded-full ${pools.length ? "bg-[#86e0b8]" : "bg-[#f79680]"}`} />{apiState} · قیمت نهایی فقط از Core می‌آید.</p></div>
        {!catalogLoading && pools.length > 1 && <div className="mt-10"><div className="text-sm font-bold text-white/70">استخر فروش را انتخاب کن</div><div className="mt-3 flex flex-wrap gap-3">{pools.map(x => <button key={x.id} onClick={() => pickPool(x.id)} aria-pressed={poolId === x.id} className={`flex items-center gap-3 rounded-2xl px-5 py-3 text-right text-sm font-extrabold transition ${poolId === x.id ? "bg-[#f7c85c] text-[#10233f]" : "bg-white/[.07] text-white ring-1 ring-white/10 hover:bg-white/[.12]"}`}>{x.name}{x.kind_label && <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-bold ${poolId === x.id ? "bg-[#10233f] text-[#f7c85c]" : "bg-white/10 text-[#86e0b8]"}`}>{x.kind_label}</span>}</button>)}</div></div>}
        {!catalogLoading && pool && manual && <div className="mt-8"><div className="text-sm font-bold text-white/70">گزینه / لوکیشن را انتخاب کن</div><div className="mt-3 flex flex-wrap gap-3">{(pool.panels || []).map(x => <button key={x.id} onClick={() => { setPanelId(x.id); setSelectedQuote(null); }} aria-pressed={panelId === x.id} className={`rounded-2xl px-5 py-3 text-sm font-extrabold transition ${panelId === x.id ? "bg-[#f7c85c] text-[#10233f]" : "bg-white/[.07] text-white ring-1 ring-white/10 hover:bg-white/[.12]"}`}>{x.label}</button>)}{!(pool.panels || []).length && <span className="text-sm text-white/60">فعلاً گزینه‌ای در این استخر موجود نیست.</span>}</div></div>}
        {!catalogLoading && pool && customName && (!manual || panelId) && <div className="mt-8 max-w-sm"><label className="block text-sm font-bold text-white/70">نام کاربری اکانت<input dir="ltr" value={accountName} onChange={e => setAccountName(e.target.value.replace(/[^A-Za-z0-9_-]/g, ""))} maxLength={32} autoComplete="off" placeholder="my_name" className="input latin mt-2 text-left !text-ink" /></label><p className={`mt-1.5 text-xs ${accountName && !NAME_RE.test(accountName) ? "text-[#f79680]" : "text-white/50"}`}>حداقل ۳ کاراکتر؛ فقط حروف انگلیسی، عدد، _ و -</p></div>}
        <div className="mt-12 grid gap-5 md:grid-cols-2 lg:grid-cols-3">
          {catalogLoading || pkgLoading ? Array.from({ length: 3 }).map((_, i) => <div key={i} className="h-72 animate-pulse rounded-3xl bg-white/10" />) :
          !pools.length ? <div className="rounded-3xl border border-white/15 bg-white/5 p-10 text-center text-white/75 md:col-span-2 lg:col-span-3"><p>سرویس‌ها موقتاً در دسترس نیست. لطفاً بعداً دوباره تلاش کنید.</p><button onClick={() => setReloadKey(k => k + 1)} className="btn mt-5 bg-white/10 text-white hover:bg-white/20"><RefreshCw size={16} />تلاش دوباره</button></div> :
          !poolId || (manual && !panelId) ? <div className="rounded-3xl border border-white/15 bg-white/5 p-10 text-center text-white/75 md:col-span-2 lg:col-span-3">{!poolId ? "برای دیدن پکیج‌ها، یک استخر فروش را انتخاب کن." : "برای دیدن پکیج‌ها، یک گزینه را انتخاب کن."}</div> :
          catalog.length ? catalog.map(p=>{const name=p.name || p.title || p.code || "Melorin"; const on = active===name; return <button key={String(p.product_id||p.id||name)} onClick={()=>choose(p)} aria-pressed={on} className={`group relative flex flex-col text-right rounded-3xl p-7 transition duration-300 hover:-translate-y-1.5 ${on?'bg-[#f7c85c] text-[#10233f] shadow-[0_24px_60px_-20px_#f7c85c88]':'bg-white/[.07] text-white ring-1 ring-white/10 hover:bg-white/[.12]'}`}>
            <div className="flex items-center justify-between"><span className="text-2xl font-black">{name}</span><span className={`grid h-9 w-9 place-items-center rounded-full ${on?'bg-[#10233f] text-[#f7c85c]':'bg-white/10 text-[#86e0b8]'}`}><Sparkles size={16} /></span></div>
            <ul className={`mt-7 space-y-3 text-sm ${on?'text-[#33466a]':'text-white/70'}`}>
              <li className="flex items-center gap-2"><Check size={15} className={on?'':'text-[#86e0b8]'} />{p.meta || `${p.duration_days ? fa(p.duration_days) : "؟"} روز · ${p.traffic_gb ? fa(p.traffic_gb) : "؟"} گیگابایت`}</li>
              <li className="flex items-center gap-2"><Check size={15} className={on?'':'text-[#86e0b8]'} />تحویل خودکار پس از پرداخت</li>
              <li className="flex items-center gap-2"><Check size={15} className={on?'':'text-[#86e0b8]'} />پرداخت از کیف پول</li>
            </ul>
            <div className="mt-auto pt-9"><div className="flex items-baseline gap-2"><span className="text-4xl font-black tracking-tight">{p.price ? new Intl.NumberFormat("fa-IR").format(p.price) : (p.display_price || "قیمت در Core")}</span><span className="text-xs opacity-60">تومان</span></div>
            <div className={`mt-5 inline-flex items-center gap-2 text-sm font-extrabold ${on?'text-[#10233f]':'text-[#f7c85c]'}`}>{on?<><Check size={16}/>انتخاب شده</>:<>مشاهده پیش‌فاکتور <ArrowLeft size={16} className="transition group-hover:-translate-x-1" /></>}</div></div>
          </button>}) : <div className="rounded-3xl border border-white/15 bg-white/5 p-10 text-center text-white/75 md:col-span-2 lg:col-span-3">این استخر فعلاً پکیجی برای فروش ندارد.</div>}
        </div></div></section>

      <section id="how" className="mx-auto max-w-6xl px-5 py-24">
        <div className="eyebrow">نحوه خرید</div><h2 className="mt-3 max-w-xl text-4xl font-black leading-tight">چهار قدم تا اتصال.</h2>
        <ol className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">{STEPS.map(([Icon, t, d], i) => <li key={t} className="card relative !p-6 transition hover:-translate-y-1 hover:shadow-lift">
          <span className="latin absolute left-5 top-4 text-5xl font-black text-ink/[.06]">{i + 1}</span>
          <span className="grid h-12 w-12 place-items-center rounded-2xl bg-accent-soft text-ink"><Icon size={22} /></span>
          <h3 className="mt-8 text-lg font-extrabold">{t}</h3><p className="mt-2 text-sm leading-7 text-muted">{d}</p></li>)}</ol>
      </section>

      <section id="why" className="mx-auto max-w-6xl px-5 pb-24"><div className="grid gap-10 lg:grid-cols-[.8fr_1.2fr]">
        <div><div className="eyebrow">چرا ملورین؟</div><h2 className="mt-3 text-4xl font-black leading-tight">کمتر تنظیم کن.<br/>بیشتر وصل باش.</h2><p className="mt-5 max-w-sm leading-8 text-muted">ملورین برای کسی ساخته شده که فقط می‌خواهد سرویسش کار کند، بدون پیچیدگی و بدون غافلگیری در صورتحساب.</p></div>
        <div className="grid gap-4 sm:grid-cols-2">{WHY.map(([Icon, t, d]) => <div key={t} className="card !p-6 transition hover:shadow-lift"><Icon className="text-coral" size={26} strokeWidth={1.8} /><h3 className="mt-6 text-lg font-extrabold">{t}</h3><p className="mt-2 text-sm leading-7 text-muted">{d}</p></div>)}</div>
      </div></section>

      <section id="account" className="px-5 pb-24"><div className="relative mx-auto max-w-6xl overflow-hidden rounded-4xl bg-mint-soft px-7 py-12 md:px-14">
        <div className="absolute -left-20 -top-24 h-64 w-64 rounded-full bg-mint/10 blur-2xl" />
        <div className="relative flex flex-col justify-between gap-8 md:flex-row md:items-center"><div><div className="text-sm font-extrabold text-mint">حساب من</div><h2 className="mt-3 text-3xl font-black">سرویس، کیف پول، سفارش‌ها.</h2><p className="mt-3 max-w-md leading-8 text-muted">{wallet ? `موجودی کیف پول: ${new Intl.NumberFormat("fa-IR").format(wallet.balance)} ${wallet.currency} · ${fa(orders.length)} سفارش` : "همه‌چیز آماده است تا از همان جایی که بودی ادامه بدهی."}</p></div><button onClick={goAccount} className="btn-primary btn-pill !px-8 !py-4">{accessToken ? "ورود به حساب" : "ورود / ثبت‌نام"} <ArrowLeft size={18} /></button></div>
      </div></section>
      <Faq/>
      </>}
    </main>

    <footer className="border-t border-line bg-surface/50"><div className="mx-auto grid max-w-6xl gap-10 px-5 py-12 md:grid-cols-[1.4fr_1fr_1fr]">
      <div><Logo /><p className="mt-4 max-w-xs text-sm leading-7 text-muted">سرویس VPN ساده، شفاف و قابل اعتماد؛ امن، روشن، بدون حاشیه.</p></div>
      <div><div className="text-sm font-extrabold">دسترسی سریع</div><ul className="mt-4 space-y-2.5 text-sm text-muted">{NAV.map(([h, l]) => <li key={h}><a className="hover:text-ink" href={inApp ? `#${h.slice(1)}` : h}>{l}</a></li>)}</ul></div>
      <div><div className="text-sm font-extrabold">حساب کاربری</div><ul className="mt-4 space-y-2.5 text-sm text-muted"><li><button onClick={goAccount} className="hover:text-ink">{accessToken ? "داشبورد" : "ورود / ثبت‌نام"}</button></li>{accessToken && <li><a className="hover:text-ink" href="#/reseller">پنل نماینده</a></li>}</ul></div>
    </div><div className="border-t border-line py-5 text-center text-xs text-muted">© ۲۰۲۶ ملورین · تمامی حقوق محفوظ است</div></footer>

    <nav aria-label="ناوبری موبایل" className="glass fixed inset-x-0 bottom-0 z-40 grid grid-cols-4 border-t border-line px-2 pb-[max(env(safe-area-inset-bottom),.5rem)] pt-2 md:hidden">
      {[[Home, "خانه", () => { window.location.hash = ""; window.scrollTo({ top: 0 }); }, !inApp], [LayoutGrid, "سرویس‌ها", () => { window.location.hash = "#plans"; }, false], [LifeBuoy, "پرسش‌ها", () => { window.location.hash = "#faq"; }, false], [User, "حساب", goAccount, inApp]].map(([Icon, l, fn, on]) => <button key={l} onClick={fn} className={`flex flex-col items-center gap-1 rounded-xl py-1.5 text-[11px] font-bold ${on ? "text-coral" : "text-muted"}`}><Icon size={20} />{l}</button>)}
    </nav>

    {modal && <Modal onClose={() => setModal("")} title={{ login: "ورود به ملورین", code: "کد ورود را وارد کن", checkout: `پیش‌فاکتور ${active}`, account: "حساب من" }[modal]}>
      {modal==="login"&&<form onSubmit={(e)=>{e.preventDefault(); validEmail && run(requestCode, "ارسال کد ناموفق بود");}}><p className="mt-2 text-sm leading-7 text-muted">رمز عبور لازم نیست؛ کد ورود به ایمیلت ارسال می‌شود. اگر حساب نداشته باشی، خودکار ساخته می‌شود.</p><label className="mt-6 block text-xs font-bold">ایمیل<div className="relative mt-1.5"><Mail size={17} className="pointer-events-none absolute right-3.5 top-1/2 -translate-y-1/2 text-muted" /><input type="email" dir="ltr" autoComplete="email" inputMode="email" value={email} onChange={e=>setEmail(e.target.value)} className="input !pr-10 text-left" placeholder="email@example.com"/></div></label><button type="submit" disabled={!validEmail || busy} className="btn-primary mt-5 w-full">{busy ? <Loader2 size={18} className="animate-spin" /> : <Mail size={18} />}ارسال کد ورود</button><p className="mt-4 flex items-center justify-center gap-1.5 text-xs text-muted"><Lock size={13} />ایمیل تو نزد ما محفوظ می‌ماند.</p></form>}
      {modal==="code"&&<form onSubmit={(e)=>{e.preventDefault(); loginCode && run(verifyCode, "کد نامعتبر است");}}><p className="mt-2 text-sm leading-7 text-muted">کد ارسال‌شده به <b className="latin text-ink">{email}</b> را وارد کن.</p><input autoFocus dir="ltr" inputMode="numeric" autoComplete="one-time-code" value={loginCode} onChange={e=>setLoginCode(e.target.value.trim())} className="input mt-6 !py-4 text-center text-2xl font-black tracking-[.5em]" placeholder="••••••" aria-label="کد ورود"/><button type="submit" disabled={!loginCode || busy} className="btn-primary mt-5 w-full">{busy && <Loader2 size={18} className="animate-spin" />}تأیید و ورود</button><button type="button" onClick={()=>setModal("login")} className="mt-3 w-full text-center text-xs font-bold text-muted hover:text-ink">تغییر ایمیل یا ارسال دوباره</button></form>}
      {modal==="checkout"&&<><p className="mt-2 text-sm text-muted">خلاصه سفارش را بررسی و از کیف پول پرداخت کن.</p><dl className="mt-6 divide-y divide-line rounded-2xl bg-surface2 px-4 text-sm"><div className="flex justify-between py-3.5"><dt className="text-muted">سرویس</dt><dd className="font-bold">{active}</dd></div>{pool && <div className="flex justify-between py-3.5"><dt className="text-muted">استخر</dt><dd className="font-bold">{pool.name}{panelLabel ? ` · ${panelLabel}` : ""}</dd></div>}{customName && <div className="flex justify-between py-3.5"><dt className="text-muted">نام کاربری</dt><dd className="latin font-bold">{accountName.trim()}</dd></div>}<div className="flex justify-between py-3.5"><dt className="text-muted">مبلغ نهایی</dt><dd className="text-lg font-black">{new Intl.NumberFormat("fa-IR").format(selectedQuote?.total||0)} <span className="text-xs font-semibold">{selectedQuote?.currency}</span></dd></div><div className="flex justify-between py-3.5"><dt className="text-muted">موجودی کیف پول</dt><dd className={`font-bold ${selectedQuote?.sufficient_funds ? "text-mint" : "text-danger"}`}>{new Intl.NumberFormat("fa-IR").format(selectedQuote?.wallet_balance||0)}</dd></div></dl>{selectedQuote && !selectedQuote.sufficient_funds && <p className="mt-3 rounded-xl bg-danger-soft px-4 py-3 text-xs font-bold leading-6 text-danger">موجودی کافی نیست. ابتدا از بخش «کیف پول» حساب را شارژ کن.</p>}<button disabled={!selectedQuote?.sufficient_funds || busy} onClick={()=>run(buySelected, "ثبت سفارش ناموفق بود")} className="btn-primary mt-5 w-full">{busy ? <Loader2 size={18} className="animate-spin" /> : <CreditCard size={18} />}پرداخت از کیف پول و ثبت سفارش</button>{selectedQuote && !selectedQuote.sufficient_funds && <button onClick={()=>{setModal(""); window.location.hash="#/dashboard";}} className="btn-soft mt-3 w-full">رفتن به کیف پول</button>}</>}
      {modal==="account"&&<><div className="mt-5 rounded-2xl bg-mint-soft p-4">موجودی: {new Intl.NumberFormat("fa-IR").format(wallet?.balance||0)} {wallet?.currency}</div><p className="mt-4 text-sm">سفارش‌ها: {fa(orders.length)}</p></>}
    </Modal>}
    <Toast message={notice} />
  </div>
}
