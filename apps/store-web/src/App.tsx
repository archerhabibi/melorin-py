import type { Rec } from './types';
// Subject + plan: Melorin storefront for VPN customers. A warm Persian service counter meets a precise account console: dusk navy, saffron, and mint; hero catalog, store-scoped quote, wallet, and orders in one calm flow.
// Design system v2: tokens live in styles.css (light + dark), shared primitives in ui.jsx.
import { Suspense, lazy, useCallback, useEffect, useState } from 'react';
import Dashboard, { Faq } from './Dashboard.tsx';
import { clearTokens, getAccessToken, setTokens } from './auth.ts';
import { publicGetOrNull } from './coreApi.ts';
import { useCoreFetch } from './useCoreFetch.ts';
import { useStoreCatalog } from './useStoreCatalog.ts';
import { googleSignOut } from './GoogleSignIn.tsx';
import TelegramLogin from './TelegramLogin.tsx';
import { PurchaseResult } from './Subscription.tsx';
import { Modal, Toast } from './ui.tsx';
import { NAME_RE, TG_ERRORS, TG_RETRY, errOf } from './landing.tsx';
import { SiteHeader } from './SiteHeader.tsx';
import { HeroSection } from './HeroSection.tsx';
import { PlansSection } from './PlansSection.tsx';
import { HowSection, WhySection } from './InfoSections.tsx';
import { AccountBanner } from './AccountBanner.tsx';
import { SiteFooter } from './SiteFooter.tsx';
import { MobileNav } from './MobileNav.tsx';
import { AccountDialog, CheckoutDialog, CodeDialog, GoogleLinkDialog, LoginDialog } from './StoreDialogs.tsx';
import type { Json } from './types';

// Reseller console is only needed by resellers: keep it out of the first-load bundle.
const Reseller = lazy(() => import('./Reseller.tsx'));

export default function App() {
  const [active, setActive] = useState('Orbit');
  const [notice, setNotice] = useState('');
  const [panelId, setPanelId] = useState('');
  const [accountName, setAccountName] = useState('');
  const [accessToken, setAccessToken] = useState(() => getAccessToken());
  const [modal, setModal] = useState('');
  const [purchasedOrder, setPurchasedOrder] = useState<Json>(null);
  const [email, setEmail] = useState('');
  const [loginCode, setLoginCode] = useState('');
  const [account, setAccount] = useState<Json>(null);
  const [wallet, setWallet] = useState<Json>(null);
  const [orders, setOrders] = useState<Json>([]);
  const [tgCfg, setTgCfg] = useState<Json>(null); // which Telegram login buttons the admin enabled (null = unknown -> legacy behaviour)
  const [selectedQuote, setSelectedQuote] = useState<Json>(null);
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
  const notify = useCallback((m: Json) => {
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
  const base = (import.meta.env?.VITE_MELORIN_API_URL || window.location.origin).replace(/\/$/, '');
  const coreFetch = useCoreFetch(base, accessToken, setAccessToken);
  const { catalog, catalogLoading, bundles, bundleId, setBundleId, pkgLoading, apiState, storeId, hasBot } =
    useStoreCatalog(coreFetch, reloadKey);
  const tgBot = hasBot && (tgCfg ? tgCfg.bot_login : true);
  const tgOidc = Boolean(tgCfg?.oidc_login && storeId);
  const showTg = tgBot || tgOidc;
  const onDash = hash === '#/dashboard' && accessToken;
  const onReseller = hash === '#/reseller' && accessToken;
  // ─── Google Sign-In ───
  function completeLogin(pair: Json) {
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
  async function handleGoogleCredential(idToken: Json) {
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
    } catch (e: Json) {
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
  const bundle = bundles.find((x: Json) => x.id === bundleId);
  const manual = bundle?.selection_mode === 'manual';
  const customName = bundle?.naming_mode === 'custom';
  const panelLabel = bundle?.panels?.find((x: Json) => x.id === panelId)?.label;
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
        ...(customName && accountName.trim() ? { account_name: accountName.trim() } : {}),
      }),
    });
    if (!r.ok) throw Error(await errOf(r, 'order failed'));
    const order = await r.json();
    setPurchasedOrder(order.id);
    setModal('delivery');
    loadAccount();
  }
  const run = async (fn: Json, failMsg: Json) => {
    setBusy(true);
    try {
      await fn();
    } catch (e: Json) {
      setNotice(
        e?.message && !/^(order failed|login request failed|invalid code)$/.test(e.message) ? e.message : failMsg,
      );
    } finally {
      setBusy(false);
    }
  };

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
      .then((r) => (r.ok ? r.json() : r.json().then((e: Json) => Promise.reject(e))))
      .then((pair: Json) => {
        setTokens(pair);
        setAccessToken(pair.access_token);
        setHash('#/dashboard');
        setAskGoogle(true);
      })
      .catch(() => {
        setNotice('لینک ورود منقضی شده است؛ دوباره از ربات تلگرام بزنید.');
        setModal('login');
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- T-W08: reviewed, dependency list intentionally limited (adding the flagged value risks refetch loops); verify in a browser before changing
  }, []);
  // After an automatic sign-in, offer the one-tap Google link (Google always needs the user's own consent) until it is linked.
  useEffect(() => {
    if (askGoogle && account) {
      setAskGoogle(false);
      if (!(account.identities || []).some((i: Json) => i.provider === 'google')) setModal('googlelink');
    }
  }, [askGoogle, account]);
  async function linkGoogleNow(idToken: Json) {
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
      .then((pair: Json) => {
        setTokens(pair);
        setAccessToken(pair.access_token);
      })
      // Opened from the bot's account button (#/dashboard) without a session: ask the visitor to sign in (Telegram / Google).
      .catch(() => {
        if (window.location.hash === '#/dashboard') setModal('login');
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- T-W08: reviewed, dependency list intentionally limited (adding the flagged value risks refetch loops); verify in a browser before changing
  }, []);
  useEffect(() => {
    if (storeId && accessToken) loadAccount();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- T-W08: reviewed, dependency list intentionally limited (adding the flagged value risks refetch loops); verify in a browser before changing
  }, [storeId, accessToken]);
  // Telegram login settings (Admin > Settings > Telegram login) and the result of a direct-login redirect (?tg_error=...).
  useEffect(() => {
    publicGetOrNull('/api/v1/auth/telegram/config')
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
    notify((TG_ERRORS as Rec)[err] || TG_ERRORS.failed);
    if (TG_RETRY.has(err)) setModal('login'); // let the visitor try again (or pick another method) right away
    // eslint-disable-next-line react-hooks/exhaustive-deps -- T-W08: reviewed, dependency list intentionally limited (adding the flagged value risks refetch loops); verify in a browser before changing
  }, []);
  const pickBundle = (id: Json) => {
    setBundleId(id);
    setPanelId('');
    setSelectedQuote(null);
    setActive('');
  };
  const choose = async (product: Json) => {
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
    if (customName && accountName.trim() && !NAME_RE.test(accountName.trim())) {
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
      <SiteHeader
        inApp={inApp}
        goAccount={goAccount}
        account={account}
        accessToken={accessToken}
        menu={menu}
        setMenu={setMenu}
      />

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
            <HeroSection />

            <PlansSection
              apiState={apiState}
              bundles={bundles}
              bundle={bundle}
              bundleId={bundleId}
              catalog={catalog}
              catalogLoading={catalogLoading}
              pkgLoading={pkgLoading}
              manual={manual}
              customName={customName}
              panelId={panelId}
              setPanelId={setPanelId}
              accountName={accountName}
              setAccountName={setAccountName}
              active={active}
              pickBundle={pickBundle}
              choose={choose}
              setSelectedQuote={setSelectedQuote}
              setReloadKey={setReloadKey}
            />

            <HowSection />

            <WhySection />

            <AccountBanner wallet={wallet} orders={orders} goAccount={goAccount} accessToken={accessToken} />
            <Faq />
          </>
        )}
      </main>

      <SiteFooter inApp={inApp} goAccount={goAccount} accessToken={accessToken} />

      <MobileNav inApp={inApp} goAccount={goAccount} />

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
            <LoginDialog
              showTg={showTg}
              base={base}
              storeId={storeId}
              tgBot={tgBot}
              tgOidc={tgOidc}
              setModal={setModal}
              email={email}
              setEmail={setEmail}
              validEmail={validEmail}
              busy={busy}
              run={run}
              requestCode={requestCode}
              handleGoogleCredential={handleGoogleCredential}
            />
          )}
          {modal === 'googlelink' && <GoogleLinkDialog linkGoogleNow={linkGoogleNow} setModal={setModal} />}
          {modal === 'delivery' && purchasedOrder && (
            <PurchaseResult orderId={purchasedOrder} storeId={storeId} coreFetch={coreFetch} notify={notify} />
          )}
          {modal === 'telegram' && (
            <TelegramLogin base={base} storeId={storeId} onTokens={completeLogin} onBack={() => setModal('login')} />
          )}
          {modal === 'code' && (
            <CodeDialog
              email={email}
              loginCode={loginCode}
              setLoginCode={setLoginCode}
              busy={busy}
              run={run}
              verifyCode={verifyCode}
              setModal={setModal}
            />
          )}
          {modal === 'checkout' && (
            <CheckoutDialog
              active={active}
              bundle={bundle}
              panelLabel={panelLabel}
              customName={customName}
              accountName={accountName}
              selectedQuote={selectedQuote}
              busy={busy}
              run={run}
              buySelected={buySelected}
              setModal={setModal}
            />
          )}
          {modal === 'account' && <AccountDialog wallet={wallet} orders={orders} />}
        </Modal>
      )}
      <Toast message={notice} />
    </div>
  );
}
