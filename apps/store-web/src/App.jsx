// Subject + plan: Melorin storefront for VPN customers. A warm Persian service counter meets a precise account console: dusk navy, saffron, and mint; hero catalog, store-scoped quote, wallet, and orders in one calm flow.
// Design system v2: tokens live in styles.css (light + dark), shared primitives in ui.jsx.
import { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowLeft,
  Check,
  CreditCard,
  Home,
  KeyRound,
  LayoutGrid,
  LifeBuoy,
  Link2,
  Loader2,
  Lock,
  Mail,
  Menu,
  RefreshCw,
  Send,
  ShieldCheck,
  Sparkles,
  User,
  Wallet as WalletIcon,
  X,
  Zap,
} from 'lucide-react';
import Dashboard, { Faq } from './Dashboard.jsx';
import { clearTokens, getAccessToken, setTokens } from './auth.js';
import { GoogleSignInButton, googleSignOut } from './GoogleSignIn.jsx';
import TelegramLogin from './TelegramLogin.jsx';
import { PurchaseResult } from './Subscription.jsx';
import TelegramLoginButtons from './TelegramLoginButtons.jsx';
import { Modal, ThemeToggle, Toast, fa } from './ui.jsx';
import { focusOnMount } from './useDialog.js';

// Reseller console is only needed by resellers: keep it out of the first-load bundle.
const Reseller = lazy(() => import('./Reseller.jsx'));

const NAV = [
  ['#plans', 'سرویس‌ها'],
  ['#how', 'نحوه خرید'],
  ['#why', 'چرا ملورین؟'],
  ['#faq', 'سوالات'],
];
const STEPS = [
  [Send, 'ورود با تلگرام یا ایمیل', 'با یک تأیید در ربات تلگرام یا با کد ایمیل؛ بدون رمز عبور.'],
  [WalletIcon, 'شارژ کیف پول', 'کارت‌به‌کارت با رسید یا درگاه آنلاین.'],
  [LayoutGrid, 'انتخاب سرویس', 'پیش‌فاکتور شفاف را ببین و پرداخت کن.'],
  [Link2, 'دریافت لینک', 'لینک اشتراک بلافاصله در حسابت آماده است.'],
];
const NAME_RE = /^[A-Za-z0-9_-]{3,}$/;
async function errOf(r, fallback) {
  try {
    const d = await r.json();
    return d?.error?.message || (typeof d?.detail === 'string' ? d.detail : '') || fallback;
  } catch {
    return fallback;
  }
}
const WHY = [
  [WalletIcon, 'کیف پول شفاف', 'شارژ، خرید و تمدید را در یک گردش مالی ساده ببین؛ هر تراکنش ردیف مشخصی دارد.'],
  [LifeBuoy, 'پشتیبانی انسانی', 'اگر جایی گیر کردی، از بخش تیکت‌ها پیام بده و پاسخ همان‌جا بیاید.'],
  [ShieldCheck, 'امنیت حساب', 'ورود با تأیید در تلگرام یا کد ایمیل، امکان ورود دومرحله‌ای و مدیریت رمز عبور.'],
  [KeyRound, 'بدون قفل شدن', 'سرویس و اطلاعاتت مال خودت است، نه یک پنل مبهم.'],
];

function Logo() {
  return (
    <a href="#/" className="flex items-center gap-3" aria-label="ملورین؛ صفحه اصلی">
      <span className="grid h-10 w-10 place-items-center rounded-2xl bg-hero text-xl font-extrabold text-[#f7c85c] shadow-soft">
        م
      </span>
      <span className="leading-tight">
        <span className="block text-lg font-extrabold">ملورین</span>
        <span className="latin block text-[10px] font-semibold tracking-[.22em] text-muted">MELORIN</span>
      </span>
    </a>
  );
}

function HeroVisual() {
  return (
    <div className="relative mx-auto w-full max-w-sm" aria-hidden="true">
      <div className="absolute -inset-6 rounded-full bg-accent/30 blur-3xl" />
      <div className="anim-float relative overflow-hidden rounded-4xl bg-hero p-6 shadow-lift">
        <div className="absolute -left-10 -top-14 h-44 w-44 rounded-full bg-[#f7c85c] opacity-70 blur-3xl" />
        <div className="relative flex items-center justify-between text-xs">
          <span className="rounded-full bg-white/10 px-3 py-1">سرویس شما</span>
          <span className="latin tracking-widest text-[#f7c85c]">MELORIN</span>
        </div>
        <div className="relative mt-10 grid place-items-center">
          <span className="absolute h-36 w-36 animate-ping rounded-full bg-[#86e0b8]/15" />
          <span className="absolute h-28 w-28 rounded-full border border-[#86e0b8]/30" />
          <span className="relative grid h-20 w-20 place-items-center rounded-full bg-[#86e0b8] text-[#0c1b33] shadow-[0_0_40px_#86e0b855]">
            <ShieldCheck size={36} strokeWidth={2} />
          </span>
        </div>
        <div className="relative mt-9 text-center">
          <div className="text-xl font-extrabold">متصل و امن</div>
          <div className="mt-1 text-xs text-white/55">یک لینک اشتراک، همه دستگاه‌ها</div>
        </div>
        <div className="relative mt-7 grid grid-cols-2 gap-3 text-xs">
          <div className="rounded-2xl bg-white/[.07] p-3">
            <div className="text-white/50">فعال‌سازی</div>
            <div className="mt-1 font-bold">پس از پرداخت</div>
          </div>
          <div className="rounded-2xl bg-white/[.07] p-3">
            <div className="text-white/50">پرداخت</div>
            <div className="mt-1 font-bold text-[#86e0b8]">کیف پول</div>
          </div>
        </div>
      </div>
      <div className="absolute -bottom-4 -right-3 flex items-center gap-2 rounded-2xl bg-[#f7c85c] px-4 py-3 text-sm font-extrabold text-[#10233f] shadow-lift">
        <Zap size={16} /> تحویل خودکار
      </div>
    </div>
  );
}

const TG_RETRY = new Set(['user_denied', 'session_expired', 'unreachable', 'failed']);
const TG_ERRORS = {
  user_denied: 'ورود در تلگرام رد شد.',
  session_expired: 'نشست ورود منقضی شد؛ دوباره امتحان کن.',
  registration_closed: 'ثبت‌نام جدید موقتاً بسته است.',
  account_disabled: 'حساب شما غیرفعال است. با پشتیبانی تماس بگیرید.',
  admin_use_panel: 'ورود ادمین فقط از پنل مدیریت انجام می‌شود.',
  unavailable: 'ورود با تلگرام در حال حاضر در دسترس نیست.',
  origin_mismatch: 'ورود با تلگرام در حال حاضر در دسترس نیست.',
  unreachable: 'اتصال به تلگرام برقرار نشد؛ کمی بعد دوباره امتحان کن.',
  failed: 'ورود با تلگرام انجام نشد؛ دوباره امتحان کن.',
};

export default function App() {
  const [active, setActive] = useState('Orbit');
  const [notice, setNotice] = useState('');
  const [catalog, setCatalog] = useState([]);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [bundles, setBundles] = useState([]);
  const [bundleId, setBundleId] = useState('');
  const [panelId, setPanelId] = useState('');
  const [accountName, setAccountName] = useState('');
  const [pkgLoading, setPkgLoading] = useState(false);
  const [apiState, setApiState] = useState('در حال اتصال به Core');
  const [accessToken, setAccessToken] = useState(() => getAccessToken());
  const [modal, setModal] = useState('');
  const [purchasedOrder, setPurchasedOrder] = useState(null);
  const [email, setEmail] = useState('');
  const [loginCode, setLoginCode] = useState('');
  const [account, setAccount] = useState(null);
  const [wallet, setWallet] = useState(null);
  const [orders, setOrders] = useState([]);
  const [storeId, setStoreId] = useState('');
  const [hasBot, setHasBot] = useState(false);
  const [tgCfg, setTgCfg] = useState(null); // which Telegram login buttons the admin enabled (null = unknown -> legacy behaviour)
  const [selectedQuote, setSelectedQuote] = useState(null);
  const [hash, setHash] = useState(window.location.hash);
  const [menu, setMenu] = useState(false);
  const [askGoogle, setAskGoogle] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  useEffect(() => {
    const h = () => {
      setHash(window.location.hash);
      setMenu(false);
    };
    window.addEventListener('hashchange', h);
    return () => window.removeEventListener('hashchange', h);
  }, []);
  const notify = useCallback((m) => {
    setNotice(m);
    setTimeout(() => setNotice(''), 2800);
  }, []);
  const logout = () => {
    googleSignOut();
    clearTokens();
    setAccessToken('');
    setAccount(null);
    setWallet(null);
    setOrders([]);
    window.location.hash = '';
  };
  const tgBot = hasBot && (tgCfg ? tgCfg.bot_login : true);
  const tgOidc = Boolean(tgCfg?.oidc_login && storeId);
  const showTg = tgBot || tgOidc;
  const onDash = hash === '#/dashboard' && accessToken;
  const onReseller = hash === '#/reseller' && accessToken;
  const base = (import.meta.env?.VITE_MELORIN_API_URL || window.location.origin).replace(/\/$/, '');
  // ─── Google Sign-In ───
  function completeLogin(pair) {
    setTokens(pair);
    setAccessToken(pair.access_token);
    setModal('');
    notify('خوش آمدی');
    if (pair.is_admin) {
      // Admins sign in on the admin panel (password + TOTP); never keep an admin session in the storefront.
      clearTokens();
      setAccessToken('');
      notify('ورود ادمین فقط از پنل مدیریت انجام می‌شود.');
      return;
    }
    window.location.hash = '#/dashboard';
  }
  async function handleGoogleCredential(idToken) {
    setBusy(true);
    try {
      const r = await fetch(`${base}/api/v1/auth/google`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id_token: idToken }),
      });
      if (!r.ok) {
        const code = (await r.json().catch(() => ({})))?.error?.code;
        throw new Error(code || 'google_failed');
      }
      completeLogin(await r.json());
    } catch (e) {
      notify(
        e.message === 'GOOGLE_NONCE_INVALID'
          ? 'نشست ورود منقضی شده بود؛ دوباره روی ورود با گوگل بزنید.'
          : e.message === 'GOOGLE_STORE_DISABLED'
            ? 'ورود با گوگل در حال حاضر فعال نیست.'
            : e.message === 'GOOGLE_UNREACHABLE'
              ? 'ارتباط سرور با گوگل برقرار نشد؛ کمی بعد دوباره تلاش کنید.'
              : 'ورود با گوگل ناموفق بود. دوباره تلاش کنید.',
      );
    } finally {
      setBusy(false);
    }
  }
  // Stable identity (so effects can list it as a dependency without re-running every render); the token is
  // read from a ref at call time, which also means callers never send a stale token.
  const accessTokenRef = useRef(accessToken);
  accessTokenRef.current = accessToken;
  const coreFetch = useCallback(
    async (path, options = {}) => {
      let token = accessTokenRef.current;
      let response = await fetch(`${base}${path}`, {
        ...options,
        credentials: 'include',
        headers: { ...(options.headers || {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      });
      if (response.status === 401) {
        {
          const rr = await fetch(`${base}/api/v1/auth/refresh`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: '{}',
          });
          if (rr.ok) {
            const pair = await rr.json();
            setTokens(pair);
            setAccessToken(pair.access_token);
            response = await fetch(`${base}${path}`, {
              ...options,
              headers: { ...(options.headers || {}), Authorization: `Bearer ${pair.access_token}` },
            });
          }
        }
      }
      return response;
    },
    [base],
  );
  async function loadAccount() {
    if (!accessToken || !storeId) return;
    try {
      const [me, w, os] = await Promise.all([
        coreFetch('/api/v1/me').then((r) => r.json()),
        coreFetch(`/api/v1/stores/${storeId}/wallet`).then((r) => r.json()),
        coreFetch(`/api/v1/stores/${storeId}/orders`).then((r) => r.json()),
      ]);
      setAccount(me);
      setWallet(w);
      setOrders(Array.isArray(os) ? os : os.items || []);
    } catch {
      setNotice('ورود را کامل کنید تا حساب نمایش داده شود');
    }
  }
  async function requestCode() {
    const r = await fetch(`${base}/api/v1/auth/email/request-code`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    });
    if (!r.ok) throw Error('login request failed');
    setModal('code');
    setNotice('کد ورود ارسال شد');
  }
  async function verifyCode() {
    const r = await fetch(`${base}/api/v1/auth/email/verify-code`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, code: loginCode }),
    });
    if (!r.ok) throw Error('invalid code');
    const pair = await r.json();
    setTokens(pair);
    setAccessToken(pair.access_token);
    setModal('');
    setNotice('خوش آمدی');
  }
  const bundle = bundles.find((x) => x.id === bundleId);
  const manual = bundle?.selection_mode === 'manual';
  const customName = bundle?.naming_mode === 'custom';
  const panelLabel = bundle?.panels?.find((x) => x.id === panelId)?.label;
  const bundleBody = () => ({ bundle_id: bundleId, ...(manual ? { selected_panel_id: panelId } : {}) });
  async function buySelected() {
    const r = await coreFetch(`/api/v1/stores/${storeId}/orders`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': `web-${crypto.randomUUID()}` },
      body: JSON.stringify({
        product_id: selectedQuote?.product_id || selectedQuote?.id,
        payment_method: 'wallet',
        kind: 'purchase',
        ...bundleBody(),
        ...(customName ? { account_name: accountName.trim() } : {}),
      }),
    });
    if (!r.ok) throw Error(await errOf(r, 'order failed'));
    const order = await r.json();
    setPurchasedOrder(order.id);
    setModal('delivery');
    loadAccount();
  }
  const run = async (fn, failMsg) => {
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setNotice(
        e?.message && !/^(order failed|login request failed|invalid code)$/.test(e.message) ? e.message : failMsg,
      );
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    const base = (import.meta.env?.VITE_MELORIN_API_URL || window.location.origin).replace(/\/$/, '');
    setCatalogLoading(true);
    // A reseller's own domain shows that reseller's store; any other host (main domain, localhost) shows the main store.
    coreFetch(`/api/v1/stores/by-domain/${encodeURIComponent(window.location.hostname.toLowerCase())}`, {
      headers: { Accept: 'application/json' },
    })
      .then((r) => (r.ok ? r : coreFetch(`/api/v1/stores/main`, { headers: { Accept: 'application/json' } })))
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((store) => {
        setStoreId(store.id);
        setHasBot(Boolean(store.bot_username));
        return fetch(`${base}/api/v1/stores/${store.id}/bundles`, { headers: { Accept: 'application/json' } });
      })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((data) => {
        const list = Array.isArray(data) ? data : data.items || [];
        setBundles(list);
        setBundleId((cur) => (list.some((x) => x.id === cur) ? cur : list.length === 1 ? list[0].id : ''));
        setApiState('اتصال Core برقرار است');
      })
      .catch(() => {
        setBundles([]);
        setApiState('Core در دسترس نیست؛ سرویس‌ها موقتاً نمایش داده نمی‌شود');
      })
      .finally(() => setCatalogLoading(false));
  }, [reloadKey, coreFetch]);
  useEffect(() => {
    setCatalog([]);
    if (!storeId || !bundleId) return;
    const base = (import.meta.env?.VITE_MELORIN_API_URL || window.location.origin).replace(/\/$/, '');
    let live = true;
    setPkgLoading(true);
    fetch(`${base}/api/v1/stores/${storeId}/bundles/${bundleId}/packages`, { headers: { Accept: 'application/json' } })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((data) => live && setCatalog(Array.isArray(data) ? data : data.items || []))
      .catch(() => live && setCatalog([]))
      .finally(() => live && setPkgLoading(false));
    return () => {
      live = false;
    };
  }, [storeId, bundleId, reloadKey]);
  // Bot account button: #/auth/handoff?t=<single-use token> signs the Telegram user in automatically (Core issues the session).
  useEffect(() => {
    const m = /^#\/auth\/handoff\?t=([\w-]+)$/.exec(window.location.hash);
    if (!m) return;
    window.history.replaceState(null, '', window.location.pathname + window.location.search + '#/dashboard'); // never leave the token in the URL/history
    fetch(`${base}/api/v1/auth/web-handoff/redeem`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: m[1] }),
    })
      .then((r) => (r.ok ? r.json() : r.json().then((e) => Promise.reject(e))))
      .then((pair) => {
        setTokens(pair);
        setAccessToken(pair.access_token);
        setHash('#/dashboard');
        setAskGoogle(true);
      })
      .catch(() => {
        setNotice('لینک ورود منقضی شده است؛ دوباره از ربات تلگرام بزنید.');
        setModal('login');
      });
  }, []);
  // After an automatic sign-in, offer the one-tap Google link (Google always needs the user's own consent) until it is linked.
  useEffect(() => {
    if (askGoogle && account) {
      setAskGoogle(false);
      if (!(account.identities || []).some((i) => i.provider === 'google')) setModal('googlelink');
    }
  }, [askGoogle, account]);
  async function linkGoogleNow(idToken) {
    const r = await coreFetch('/api/v1/me/identities/google', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id_token: idToken }),
    });
    if (r.ok) {
      setModal('');
      notify('حساب گوگل متصل شد');
      loadAccount();
    } else notify(r.status === 409 ? 'این حساب گوگل به حساب دیگری متصل است' : 'اتصال گوگل ناموفق بود');
  }
  useEffect(() => {
    if (accessToken || /^#\/auth\/handoff/.test(window.location.hash)) return;
    fetch(`${base}/api/v1/auth/refresh`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((pair) => {
        setTokens(pair);
        setAccessToken(pair.access_token);
      })
      // Opened from the bot's account button (#/dashboard) without a session: ask the visitor to sign in (Telegram / Google).
      .catch(() => {
        if (window.location.hash === '#/dashboard') setModal('login');
      });
  }, []);
  useEffect(() => {
    if (storeId && accessToken) loadAccount();
  }, [storeId, accessToken]);
  // Telegram login settings (Admin > Settings > Telegram login) and the result of a direct-login redirect (?tg_error=...).
  useEffect(() => {
    fetch(`${base}/api/v1/auth/telegram/config`, { headers: { Accept: 'application/json' } })
      .then((r) => (r.ok ? r.json() : null))
      .then(setTgCfg)
      .catch(() => {});
    const q = new URLSearchParams(window.location.search);
    const err = q.get('tg_error');
    if (!err) return;
    q.delete('tg_error');
    window.history.replaceState(
      null,
      '',
      window.location.pathname + (q.toString() ? `?${q}` : '') + window.location.hash,
    );
    notify(TG_ERRORS[err] || TG_ERRORS.failed);
    if (TG_RETRY.has(err)) setModal('login'); // let the visitor try again (or pick another method) right away
  }, []);
  const pickBundle = (id) => {
    setBundleId(id);
    setPanelId('');
    setSelectedQuote(null);
    setActive('');
  };
  const choose = async (product) => {
    const name = product.name || product.title || product.code;
    setActive(name);
    if (!accessToken) {
      setModal('login');
      setNotice('برای خرید وارد شوید');
      return;
    }
    if (!bundleId || (manual && !panelId)) {
      setNotice('ابتدا بسته فروش و گزینه را انتخاب کنید');
      return;
    }
    if (customName && !NAME_RE.test(accountName.trim())) {
      setNotice('نام کاربری حداقل ۳ کاراکتر و فقط شامل حروف انگلیسی، عدد، _ و - باشد');
      return;
    }
    try {
      const r = await coreFetch(`/api/v1/stores/${storeId}/checkout/quote`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ product_id: product.product_id || product.id, ...bundleBody() }),
      });
      if (!r.ok) {
        setNotice(await errOf(r, 'پیش‌فاکتور از Core دریافت نشد'));
        return;
      }
      const q = await r.json();
      setSelectedQuote({ product_id: product.product_id || product.id, ...q });
      setModal('checkout');
    } catch {
      setNotice('پیش‌فاکتور از Core دریافت نشد');
    }
  };
  const goAccount = () => (accessToken ? (window.location.hash = '#/dashboard') : setModal('login'));
  const validEmail = /^\S+@\S+\.\S+$/.test(email.trim());
  const inApp = onDash || onReseller;

  return (
    <div className="min-h-screen" dir="rtl">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:right-4 focus:top-4 focus:z-[70] focus:rounded-xl focus:bg-surface focus:px-4 focus:py-2"
      >
        پرش به محتوا
      </a>
      <header className="glass sticky top-0 z-40 border-b border-line/70">
        <div className="mx-auto flex h-[68px] max-w-6xl items-center justify-between gap-4 px-5">
          <Logo />
          <nav className="hidden items-center gap-1 text-sm font-semibold md:flex" aria-label="ناوبری اصلی">
            {NAV.map(([h, l]) => (
              <a
                key={h}
                href={inApp ? `#${h.slice(1)}` : h}
                className="rounded-full px-4 py-2 text-muted transition hover:bg-surface2 hover:text-ink"
              >
                {l}
              </a>
            ))}
          </nav>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <button onClick={goAccount} className="btn-primary btn-pill hidden !py-2.5 sm:inline-flex">
              <User size={16} />
              {account?.display_name || (accessToken ? 'حساب من' : 'ورود / ثبت‌نام')}
            </button>
            <button
              onClick={() => setMenu(!menu)}
              aria-label="منو"
              aria-expanded={menu}
              className="grid h-10 w-10 place-items-center rounded-full ring-1 ring-line md:hidden"
            >
              {menu ? <X size={18} /> : <Menu size={18} />}
            </button>
          </div>
        </div>
        {menu && (
          <div className="anim-pop border-t border-line px-5 pb-5 pt-3 md:hidden">
            <nav className="grid gap-1 text-sm font-bold">
              {NAV.map(([h, l]) => (
                <a key={h} href={h} onClick={() => setMenu(false)} className="rounded-xl px-3 py-3 hover:bg-surface2">
                  {l}
                </a>
              ))}
              <button
                onClick={() => {
                  setMenu(false);
                  goAccount();
                }}
                className="btn-primary mt-2"
              >
                <User size={16} />
                {accessToken ? 'حساب من' : 'ورود / ثبت‌نام'}
              </button>
            </nav>
          </div>
        )}
      </header>

      <main id="main" className="pb-24 md:pb-0">
        {onReseller ? (
          <Suspense
            fallback={
              <div className="py-24 text-center text-sm opacity-70" role="status" aria-live="polite">
                در حال بارگذاری…
              </div>
            }
          >
            <Reseller coreFetch={coreFetch} notify={notify} />
          </Suspense>
        ) : onDash ? (
          <Dashboard
            coreFetch={coreFetch}
            storeId={storeId}
            account={account}
            wallet={wallet}
            orders={orders}
            reload={loadAccount}
            notify={notify}
            onLogout={logout}
          />
        ) : (
          <>
            <section className="hero-bg relative overflow-hidden">
              <div className="grid-dots absolute inset-0" />
              <div className="relative mx-auto grid max-w-6xl gap-14 px-5 pb-24 pt-14 md:grid-cols-[1.1fr_.9fr] md:items-center md:pt-20">
                <div className="anim-rise">
                  <div className="inline-flex items-center gap-2 rounded-full bg-mint-soft px-4 py-2 text-xs font-extrabold text-mint">
                    <span className="relative flex h-2 w-2">
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-mint opacity-60" />
                      <span className="relative inline-flex h-2 w-2 rounded-full bg-mint" />
                    </span>
                    شبکه پایدار، بدون پیچیدگی
                  </div>
                  <h1 className="mt-6 text-[2.6rem] font-black leading-[1.18] tracking-tight sm:text-6xl md:text-7xl">
                    اینترنتت را{' '}
                    <span className="relative whitespace-nowrap text-coral">
                      آزادتر
                      <svg
                        aria-hidden="true"
                        viewBox="0 0 220 12"
                        className="absolute -bottom-2 right-0 h-3 w-full text-accent"
                        preserveAspectRatio="none"
                      >
                        <path
                          d="M2 8c40-7 90-7 216-1"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="5"
                          strokeLinecap="round"
                        />
                      </svg>
                    </span>
                    <br />
                    انتخاب کن.
                  </h1>
                  <p className="mt-7 max-w-lg text-lg leading-9 text-muted">
                    سرویس VPN ساده، سریع و قابل تمدید. قیمت‌گذاری شفاف، کیف پول امن و پشتیبانی واقعی، همه در یک جا.
                  </p>
                  <div className="mt-9 flex flex-wrap gap-3">
                    <a href="#plans" className="btn-primary btn-pill !px-8 !py-4">
                      دیدن سرویس‌ها <ArrowLeft size={18} />
                    </a>
                    <a href="#how" className="btn-soft btn-pill !px-8 !py-4">
                      چطور کار می‌کند؟
                    </a>
                  </div>
                  <ul className="mt-10 flex flex-wrap gap-x-7 gap-y-3 text-sm font-semibold text-muted">
                    {['تحویل خودکار', 'پرداخت با کیف پول', 'پشتیبانی تیکتی'].map((t) => (
                      <li key={t} className="flex items-center gap-2">
                        <span className="grid h-5 w-5 place-items-center rounded-full bg-mint-soft text-mint">
                          <Check size={13} strokeWidth={3} />
                        </span>
                        {t}
                      </li>
                    ))}
                  </ul>
                </div>
                <div className="anim-rise [animation-delay:.15s]">
                  <HeroVisual />
                </div>
              </div>
            </section>

            <section id="plans" className="bg-hero px-5 py-24">
              <div className="mx-auto max-w-6xl">
                <div className="flex flex-col justify-between gap-5 md:flex-row md:items-end">
                  <div>
                    <div className="text-sm font-extrabold text-[#f7c85c]">سرویس‌ها</div>
                    <h2 className="mt-3 text-4xl font-black leading-tight">برای ریتم خودت انتخاب کن.</h2>
                  </div>
                  <p className="flex max-w-sm items-center gap-2 text-sm leading-7 text-white/60">
                    <span
                      className={`h-2 w-2 shrink-0 rounded-full ${bundles.length ? 'bg-[#86e0b8]' : 'bg-[#f79680]'}`}
                    />
                    {apiState} · قیمت نهایی فقط از Core می‌آید.
                  </p>
                </div>
                {!catalogLoading && bundles.length > 1 && (
                  <div className="mt-10">
                    <div className="text-sm font-bold text-white/70">بسته فروش را انتخاب کن</div>
                    <div className="mt-3 flex flex-wrap gap-3">
                      {bundles.map((x) => (
                        <button
                          key={x.id}
                          onClick={() => pickBundle(x.id)}
                          aria-pressed={bundleId === x.id}
                          className={`flex items-center gap-3 rounded-2xl px-5 py-3 text-right text-sm font-extrabold transition ${bundleId === x.id ? 'bg-[#f7c85c] text-[#10233f]' : 'bg-white/[.07] text-white ring-1 ring-white/10 hover:bg-white/[.12]'}`}
                        >
                          {x.name}
                          {x.kind_label && (
                            <span
                              className={`rounded-full px-2.5 py-0.5 text-[11px] font-bold ${bundleId === x.id ? 'bg-[#10233f] text-[#f7c85c]' : 'bg-white/10 text-[#86e0b8]'}`}
                            >
                              {x.kind_label}
                            </span>
                          )}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {!catalogLoading && bundle && manual && (
                  <div className="mt-8">
                    <div className="text-sm font-bold text-white/70">گزینه / لوکیشن را انتخاب کن</div>
                    <div className="mt-3 flex flex-wrap gap-3">
                      {(bundle.panels || []).map((x) => (
                        <button
                          key={x.id}
                          onClick={() => {
                            setPanelId(x.id);
                            setSelectedQuote(null);
                          }}
                          aria-pressed={panelId === x.id}
                          className={`rounded-2xl px-5 py-3 text-sm font-extrabold transition ${panelId === x.id ? 'bg-[#f7c85c] text-[#10233f]' : 'bg-white/[.07] text-white ring-1 ring-white/10 hover:bg-white/[.12]'}`}
                        >
                          {x.label}
                        </button>
                      ))}
                      {!(bundle.panels || []).length && (
                        <span className="text-sm text-white/60">فعلاً گزینه‌ای در این بسته موجود نیست.</span>
                      )}
                    </div>
                  </div>
                )}
                {!catalogLoading && bundle && customName && (!manual || panelId) && (
                  <div className="mt-8 max-w-sm">
                    <label className="block text-sm font-bold text-white/70">
                      نام کاربری اکانت
                      <input
                        dir="ltr"
                        value={accountName}
                        onChange={(e) => setAccountName(e.target.value.replace(/[^A-Za-z0-9_-]/g, ''))}
                        maxLength={32}
                        autoComplete="off"
                        placeholder="my_name"
                        className="input latin mt-2 text-left !text-ink"
                      />
                    </label>
                    <p
                      className={`mt-1.5 text-xs ${accountName && !NAME_RE.test(accountName) ? 'text-[#f79680]' : 'text-white/50'}`}
                    >
                      حداقل ۳ کاراکتر؛ فقط حروف انگلیسی، عدد، _ و -
                    </p>
                  </div>
                )}
                <div className="mt-12 grid gap-5 md:grid-cols-2 lg:grid-cols-3">
                  {catalogLoading || pkgLoading ? (
                    Array.from({ length: 3 }).map((_, i) => (
                      <div key={i} className="h-72 animate-pulse rounded-3xl bg-white/10" />
                    ))
                  ) : !bundles.length ? (
                    <div className="rounded-3xl border border-white/15 bg-white/5 p-10 text-center text-white/75 md:col-span-2 lg:col-span-3">
                      <p>سرویس‌ها موقتاً در دسترس نیست. لطفاً بعداً دوباره تلاش کنید.</p>
                      <button
                        onClick={() => setReloadKey((k) => k + 1)}
                        className="btn mt-5 bg-white/10 text-white hover:bg-white/20"
                      >
                        <RefreshCw size={16} />
                        تلاش دوباره
                      </button>
                    </div>
                  ) : !bundleId || (manual && !panelId) ? (
                    <div className="rounded-3xl border border-white/15 bg-white/5 p-10 text-center text-white/75 md:col-span-2 lg:col-span-3">
                      {!bundleId
                        ? 'برای دیدن پکیج‌ها، یک بسته فروش را انتخاب کن.'
                        : 'برای دیدن پکیج‌ها، یک گزینه را انتخاب کن.'}
                    </div>
                  ) : catalog.length ? (
                    catalog.map((p) => {
                      const name = p.name || p.title || p.code || 'Melorin';
                      const on = active === name;
                      return (
                        <button
                          key={String(p.product_id || p.id || name)}
                          onClick={() => choose(p)}
                          aria-pressed={on}
                          className={`group relative flex flex-col text-right rounded-3xl p-7 transition duration-300 hover:-translate-y-1.5 ${on ? 'bg-[#f7c85c] text-[#10233f] shadow-[0_24px_60px_-20px_#f7c85c88]' : 'bg-white/[.07] text-white ring-1 ring-white/10 hover:bg-white/[.12]'}`}
                        >
                          <div className="flex items-center justify-between">
                            <span className="text-2xl font-black">{name}</span>
                            <span
                              className={`grid h-9 w-9 place-items-center rounded-full ${on ? 'bg-[#10233f] text-[#f7c85c]' : 'bg-white/10 text-[#86e0b8]'}`}
                            >
                              <Sparkles size={16} />
                            </span>
                          </div>
                          <ul className={`mt-7 space-y-3 text-sm ${on ? 'text-[#33466a]' : 'text-white/70'}`}>
                            <li className="flex items-center gap-2">
                              <Check size={15} className={on ? '' : 'text-[#86e0b8]'} />
                              {p.meta ||
                                `${p.duration_days ? fa(p.duration_days) : '؟'} روز · ${p.traffic_gb ? fa(p.traffic_gb) : '؟'} گیگابایت`}
                            </li>
                            <li className="flex items-center gap-2">
                              <Check size={15} className={on ? '' : 'text-[#86e0b8]'} />
                              تحویل خودکار پس از پرداخت
                            </li>
                            <li className="flex items-center gap-2">
                              <Check size={15} className={on ? '' : 'text-[#86e0b8]'} />
                              پرداخت از کیف پول
                            </li>
                          </ul>
                          <div className="mt-auto pt-9">
                            <div className="flex items-baseline gap-2">
                              <span className="text-4xl font-black tracking-tight">
                                {p.price
                                  ? new Intl.NumberFormat('fa-IR').format(p.price)
                                  : p.display_price || 'قیمت در Core'}
                              </span>
                              <span className="text-xs opacity-60">تومان</span>
                            </div>
                            <div
                              className={`mt-5 inline-flex items-center gap-2 text-sm font-extrabold ${on ? 'text-[#10233f]' : 'text-[#f7c85c]'}`}
                            >
                              {on ? (
                                <>
                                  <Check size={16} />
                                  انتخاب شده
                                </>
                              ) : (
                                <>
                                  مشاهده پیش‌فاکتور{' '}
                                  <ArrowLeft size={16} className="transition group-hover:-translate-x-1" />
                                </>
                              )}
                            </div>
                          </div>
                        </button>
                      );
                    })
                  ) : (
                    <div className="rounded-3xl border border-white/15 bg-white/5 p-10 text-center text-white/75 md:col-span-2 lg:col-span-3">
                      این بسته فعلاً پکیجی برای فروش ندارد.
                    </div>
                  )}
                </div>
              </div>
            </section>

            <section id="how" className="mx-auto max-w-6xl px-5 py-24">
              <div className="eyebrow">نحوه خرید</div>
              <h2 className="mt-3 max-w-xl text-4xl font-black leading-tight">چهار قدم تا اتصال.</h2>
              <ol className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
                {STEPS.map(([Icon, t, d], i) => (
                  <li key={t} className="card relative !p-6 transition hover:-translate-y-1 hover:shadow-lift">
                    <span className="latin absolute left-5 top-4 text-5xl font-black text-ink/[.06]">{i + 1}</span>
                    <span className="grid h-12 w-12 place-items-center rounded-2xl bg-accent-soft text-ink">
                      <Icon size={22} />
                    </span>
                    <h3 className="mt-8 text-lg font-extrabold">{t}</h3>
                    <p className="mt-2 text-sm leading-7 text-muted">{d}</p>
                  </li>
                ))}
              </ol>
            </section>

            <section id="why" className="mx-auto max-w-6xl px-5 pb-24">
              <div className="grid gap-10 lg:grid-cols-[.8fr_1.2fr]">
                <div>
                  <div className="eyebrow">چرا ملورین؟</div>
                  <h2 className="mt-3 text-4xl font-black leading-tight">
                    کمتر تنظیم کن.
                    <br />
                    بیشتر وصل باش.
                  </h2>
                  <p className="mt-5 max-w-sm leading-8 text-muted">
                    ملورین برای کسی ساخته شده که فقط می‌خواهد سرویسش کار کند، بدون پیچیدگی و بدون غافلگیری در صورتحساب.
                  </p>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  {WHY.map(([Icon, t, d]) => (
                    <div key={t} className="card !p-6 transition hover:shadow-lift">
                      <Icon className="text-coral" size={26} strokeWidth={1.8} />
                      <h3 className="mt-6 text-lg font-extrabold">{t}</h3>
                      <p className="mt-2 text-sm leading-7 text-muted">{d}</p>
                    </div>
                  ))}
                </div>
              </div>
            </section>

            <section id="account" className="px-5 pb-24">
              <div className="relative mx-auto max-w-6xl overflow-hidden rounded-4xl bg-mint-soft px-7 py-12 md:px-14">
                <div className="absolute -left-20 -top-24 h-64 w-64 rounded-full bg-mint/10 blur-2xl" />
                <div className="relative flex flex-col justify-between gap-8 md:flex-row md:items-center">
                  <div>
                    <div className="text-sm font-extrabold text-mint">حساب من</div>
                    <h2 className="mt-3 text-3xl font-black">سرویس، کیف پول، سفارش‌ها.</h2>
                    <p className="mt-3 max-w-md leading-8 text-muted">
                      {wallet
                        ? `موجودی کیف پول: ${new Intl.NumberFormat('fa-IR').format(wallet.balance)} ${wallet.currency} · ${fa(orders.length)} سفارش`
                        : 'همه‌چیز آماده است تا از همان جایی که بودی ادامه بدهی.'}
                    </p>
                  </div>
                  <button onClick={goAccount} className="btn-primary btn-pill !px-8 !py-4">
                    {accessToken ? 'ورود به حساب' : 'ورود / ثبت‌نام'} <ArrowLeft size={18} />
                  </button>
                </div>
              </div>
            </section>
            <Faq />
          </>
        )}
      </main>

      <footer className="border-t border-line bg-surface/50">
        <div className="mx-auto grid max-w-6xl gap-10 px-5 py-12 md:grid-cols-[1.4fr_1fr_1fr]">
          <div>
            <Logo />
            <p className="mt-4 max-w-xs text-sm leading-7 text-muted">
              سرویس VPN ساده، شفاف و قابل اعتماد؛ امن، روشن، بدون حاشیه.
            </p>
          </div>
          <div>
            <div className="text-sm font-extrabold">دسترسی سریع</div>
            <ul className="mt-4 space-y-2.5 text-sm text-muted">
              {NAV.map(([h, l]) => (
                <li key={h}>
                  <a className="hover:text-ink" href={inApp ? `#${h.slice(1)}` : h}>
                    {l}
                  </a>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <div className="text-sm font-extrabold">حساب کاربری</div>
            <ul className="mt-4 space-y-2.5 text-sm text-muted">
              <li>
                <button onClick={goAccount} className="hover:text-ink">
                  {accessToken ? 'داشبورد' : 'ورود / ثبت‌نام'}
                </button>
              </li>
              {accessToken && (
                <li>
                  <a className="hover:text-ink" href="#/reseller">
                    پنل نماینده
                  </a>
                </li>
              )}
            </ul>
          </div>
        </div>
        <div className="border-t border-line py-5 text-center text-xs text-muted">
          © ۲۰۲۶ ملورین · تمامی حقوق محفوظ است
        </div>
      </footer>

      <nav
        aria-label="ناوبری موبایل"
        className="glass fixed inset-x-0 bottom-0 z-40 grid grid-cols-4 border-t border-line px-2 pb-[max(env(safe-area-inset-bottom),.5rem)] pt-2 md:hidden"
      >
        {[
          [
            Home,
            'خانه',
            () => {
              window.location.hash = '';
              window.scrollTo({ top: 0 });
            },
            !inApp,
          ],
          [
            LayoutGrid,
            'سرویس‌ها',
            () => {
              window.location.hash = '#plans';
            },
            false,
          ],
          [
            LifeBuoy,
            'پرسش‌ها',
            () => {
              window.location.hash = '#faq';
            },
            false,
          ],
          [User, 'حساب', goAccount, inApp],
        ].map(([Icon, l, fn, on]) => (
          <button
            key={l}
            onClick={fn}
            className={`flex flex-col items-center gap-1 rounded-xl py-1.5 text-[11px] font-bold ${on ? 'text-coral' : 'text-muted'}`}
          >
            <Icon size={20} />
            {l}
          </button>
        ))}
      </nav>

      {modal && (
        <Modal
          onClose={() => setModal('')}
          title={
            {
              login: 'ورود به ملورین',
              telegram: 'ورود با تلگرام',
              code: 'کد ورود را وارد کن',
              checkout: `پیش‌فاکتور ${active}`,
              account: 'حساب من',
              googlelink: 'اتصال حساب گوگل',
              delivery: 'اکانت شما',
            }[modal]
          }
        >
          {modal === 'login' && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                validEmail && run(requestCode, 'ارسال کد ناموفق بود');
              }}
            >
              <p className="mt-2 text-sm leading-7 text-muted">
                رمز عبور لازم نیست؛ با تأیید در تلگرام یا کدی که به ایمیلت می‌آید وارد شو. اگر حساب نداشته باشی، خودکار
                ساخته می‌شود.
              </p>
              {showTg && (
                <>
                  <TelegramLoginButtons
                    base={base}
                    storeId={storeId}
                    bot={tgBot}
                    direct={tgOidc}
                    onBot={() => setModal('telegram')}
                  />
                  <div className="mt-4 flex items-center gap-3">
                    <span className="h-px flex-1 bg-line" />
                    <span className="text-xs text-muted">یا با ایمیل</span>
                    <span className="h-px flex-1 bg-line" />
                  </div>
                </>
              )}
              <label className={`${showTg ? 'mt-4' : 'mt-6'} block text-xs font-bold`}>
                ایمیل
                <div className="relative mt-1.5">
                  <Mail
                    size={17}
                    className="pointer-events-none absolute right-3.5 top-1/2 -translate-y-1/2 text-muted"
                  />
                  <input
                    type="email"
                    dir="ltr"
                    autoComplete="email"
                    inputMode="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="input !pr-10 text-left"
                    placeholder="email@example.com"
                  />
                </div>
              </label>
              <button type="submit" disabled={!validEmail || busy} className="btn-primary mt-5 w-full">
                {busy ? <Loader2 size={18} className="animate-spin" /> : <Mail size={18} />}ارسال کد ورود
              </button>
              <p className="mt-4 flex items-center justify-center gap-1.5 text-xs text-muted">
                <Lock size={13} />
                ایمیل تو نزد ما محفوظ می‌ماند.
              </p>
              <div className="my-4 flex items-center gap-3">
                <span className="h-px flex-1 bg-line" />
                <span className="text-xs text-muted">یا</span>
                <span className="h-px flex-1 bg-line" />
              </div>
              <GoogleSignInButton onCredential={handleGoogleCredential} text="continue_with" disabled={busy} />
            </form>
          )}
          {modal === 'googlelink' && (
            <div>
              <p className="mt-2 text-sm leading-7 text-muted">
                با ورود شما از تلگرام وارد شدید. برای اینکه با گوگل هم به همین حساب برسید، یک‌بار حساب گوگل‌تان را تأیید
                کنید.
              </p>
              <GoogleSignInButton onCredential={linkGoogleNow} text="continue_with" className="mt-4" />
              <button onClick={() => setModal('')} className="btn-soft mt-4 w-full">
                بعداً
              </button>
            </div>
          )}
          {modal === 'delivery' && purchasedOrder && (
            <PurchaseResult orderId={purchasedOrder} storeId={storeId} coreFetch={coreFetch} notify={notify} />
          )}
          {modal === 'telegram' && (
            <TelegramLogin base={base} storeId={storeId} onTokens={completeLogin} onBack={() => setModal('login')} />
          )}
          {modal === 'code' && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                loginCode && run(verifyCode, 'کد نامعتبر است');
              }}
            >
              <p className="mt-2 text-sm leading-7 text-muted">
                کد ارسال‌شده به <b className="latin text-ink">{email}</b> را وارد کن.
              </p>
              <input
                ref={focusOnMount}
                dir="ltr"
                inputMode="numeric"
                autoComplete="one-time-code"
                value={loginCode}
                onChange={(e) => setLoginCode(e.target.value.trim())}
                className="input mt-6 !py-4 text-center text-2xl font-black tracking-[.5em]"
                placeholder="••••••"
                aria-label="کد ورود"
              />
              <button type="submit" disabled={!loginCode || busy} className="btn-primary mt-5 w-full">
                {busy && <Loader2 size={18} className="animate-spin" />}تأیید و ورود
              </button>
              <button
                type="button"
                onClick={() => setModal('login')}
                className="mt-3 w-full text-center text-xs font-bold text-muted hover:text-ink"
              >
                تغییر ایمیل یا ارسال دوباره
              </button>
            </form>
          )}
          {modal === 'checkout' && (
            <>
              <p className="mt-2 text-sm text-muted">خلاصه سفارش را بررسی و از کیف پول پرداخت کن.</p>
              <dl className="mt-6 divide-y divide-line rounded-2xl bg-surface2 px-4 text-sm">
                <div className="flex justify-between py-3.5">
                  <dt className="text-muted">سرویس</dt>
                  <dd className="font-bold">{active}</dd>
                </div>
                {bundle && (
                  <div className="flex justify-between py-3.5">
                    <dt className="text-muted">بسته</dt>
                    <dd className="font-bold">
                      {bundle.name}
                      {panelLabel ? ` · ${panelLabel}` : ''}
                    </dd>
                  </div>
                )}
                {customName && (
                  <div className="flex justify-between py-3.5">
                    <dt className="text-muted">نام کاربری</dt>
                    <dd className="latin font-bold">{accountName.trim()}</dd>
                  </div>
                )}
                <div className="flex justify-between py-3.5">
                  <dt className="text-muted">مبلغ نهایی</dt>
                  <dd className="text-lg font-black">
                    {new Intl.NumberFormat('fa-IR').format(selectedQuote?.total || 0)}{' '}
                    <span className="text-xs font-semibold">{selectedQuote?.currency}</span>
                  </dd>
                </div>
                <div className="flex justify-between py-3.5">
                  <dt className="text-muted">موجودی کیف پول</dt>
                  <dd className={`font-bold ${selectedQuote?.sufficient_funds ? 'text-mint' : 'text-danger'}`}>
                    {new Intl.NumberFormat('fa-IR').format(selectedQuote?.wallet_balance || 0)}
                  </dd>
                </div>
              </dl>
              {selectedQuote && !selectedQuote.sufficient_funds && (
                <p className="mt-3 rounded-xl bg-danger-soft px-4 py-3 text-xs font-bold leading-6 text-danger">
                  موجودی کافی نیست. ابتدا از بخش «کیف پول» حساب را شارژ کن.
                </p>
              )}
              <button
                disabled={!selectedQuote?.sufficient_funds || busy}
                onClick={() => run(buySelected, 'ثبت سفارش ناموفق بود')}
                className="btn-primary mt-5 w-full"
              >
                {busy ? <Loader2 size={18} className="animate-spin" /> : <CreditCard size={18} />}پرداخت از کیف پول و
                ثبت سفارش
              </button>
              {selectedQuote && !selectedQuote.sufficient_funds && (
                <button
                  onClick={() => {
                    setModal('');
                    window.location.hash = '#/dashboard';
                  }}
                  className="btn-soft mt-3 w-full"
                >
                  رفتن به کیف پول
                </button>
              )}
            </>
          )}
          {modal === 'account' && (
            <>
              <div className="mt-5 rounded-2xl bg-mint-soft p-4">
                موجودی: {new Intl.NumberFormat('fa-IR').format(wallet?.balance || 0)} {wallet?.currency}
              </div>
              <p className="mt-4 text-sm">سفارش‌ها: {fa(orders.length)}</p>
            </>
          )}
        </Modal>
      )}
      <Toast message={notice} />
    </div>
  );
}
