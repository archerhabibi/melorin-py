import { useEffect, useState } from 'react';
import { Bell, ChevronDown, LogOut, Package, Store, Wallet as WalletIcon, ArrowRight } from 'lucide-react';
import { GoogleSignInButton } from './GoogleSignIn.jsx';
import Loyalty from './Loyalty.jsx';
import Referral from './Referral.jsx';
import { Empty, Loading, PageTitle, PasswordInput, fa, fd } from './ui.jsx';
import { J, tabs, card, btn, inp, Orders, Vpn } from './dashboard/DashboardAccounts.jsx';
import { Wallet } from './dashboard/DashboardWallet.jsx';
import { Tickets } from './dashboard/DashboardTickets.jsx';

export { Wallet } from './dashboard/DashboardWallet.jsx';
export { Tickets } from './dashboard/DashboardTickets.jsx';

function Notifications({ coreFetch, storeId, notify, onCount }) {
  const [d, setD] = useState(null);
  const load = () =>
    coreFetch(`/api/v1/stores/${storeId}/notifications`)
      .then((r) => r.json())
      .then((x) => {
        setD(x);
        onCount?.(x.unread);
      })
      .catch(() => setD({ items: [], unread: 0 }));
  useEffect(() => {
    load();
  }, []);
  const read = async (n) => {
    if (!n.read) {
      await coreFetch(`/api/v1/stores/${storeId}/notifications/${n.id}/read`, { method: 'POST' });
      load();
    }
  };
  const all = async () => {
    const r = await coreFetch(`/api/v1/stores/${storeId}/notifications/read-all`, { method: 'POST' });
    r.ok ? load() : notify('ناموفق بود');
  };
  if (!d) return <Loading rows={3} />;
  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <span className="text-sm text-muted">{fa(d.unread)} اعلان خوانده‌نشده</span>
        <button
          disabled={!d.unread}
          onClick={all}
          className="rounded-lg border border-line px-3 py-1.5 text-xs font-bold disabled:opacity-40"
        >
          علامت‌گذاری همه
        </button>
      </div>
      {d.items.length ? (
        <div className="space-y-2">
          {d.items.map((n) => (
            <button
              key={n.id}
              onClick={() => read(n)}
              className={`${card} block w-full text-right ${n.read ? 'opacity-60' : 'border-coral'}`}
            >
              <div className="flex justify-between">
                <b>{n.title}</b>
                {!n.read && <span className="h-2 w-2 rounded-full bg-coral" />}
              </div>
              <p className="mt-1 text-sm leading-7 text-muted">{n.body}</p>
              <div className="mt-1 text-[10px] text-muted">{fd(n.created_at)}</div>
            </button>
          ))}
        </div>
      ) : (
        <Empty text="اعلانی ندارید." />
      )}
    </div>
  );
}

function Profile({ coreFetch, storeId, account, notify, reload }) {
  const [name, setName] = useState(account?.display_name || '');
  const [link, setLink] = useState(null);
  const [pw, setPw] = useState('');
  const [totp, setTotp] = useState(null);
  const [code, setCode] = useState('');
  const post = (p, body) => coreFetch(p, { method: 'POST', headers: J, body: body ? JSON.stringify(body) : undefined });
  async function saveName() {
    const r = await coreFetch('/api/v1/me', {
      method: 'PATCH',
      headers: J,
      body: JSON.stringify({ display_name: name }),
    });
    notify(r.ok ? 'ذخیره شد' : 'ذخیره ناموفق بود');
    r.ok && reload();
  }
  async function tg() {
    const r = await post('/api/v1/me/link-codes/telegram');
    r.ok ? setLink(await r.json()) : notify('ساخت کد ناموفق بود');
  }
  async function linkGoogle(idToken) {
    const r = await post('/api/v1/me/identities/google', { id_token: idToken });
    if (r.ok) {
      notify('حساب گوگل متصل شد');
      reload();
    } else notify(r.status === 409 ? 'این حساب گوگل به حساب دیگری متصل است' : 'اتصال گوگل ناموفق بود');
  }
  const googleLinked = (account?.identities || []).some((i) => i.provider === 'google');
  async function setPass() {
    const r = await post('/api/v1/me/password', { password: pw });
    notify(r.ok ? 'رمز عبور تنظیم شد' : 'رمز نامعتبر است (حداقل ۸ کاراکتر)');
    r.ok && setPw('');
  }
  async function setup2fa() {
    const r = await post('/api/v1/me/2fa/setup');
    r.ok ? setTotp(await r.json()) : notify('راه‌اندازی ناموفق بود');
  }
  async function enable2fa() {
    const r = await post('/api/v1/me/2fa/enable', { code });
    if (r.ok) {
      notify('۲FA فعال شد');
      setTotp(null);
      setCode('');
      reload();
    } else notify('کد نادرست است');
  }
  return (
    <div className="grid gap-5 md:grid-cols-2">
      <div className={card}>
        <h4 className="font-extrabold">پروفایل</h4>
        <div className="mt-2 text-xs text-muted">{account?.email || 'ایمیل ثبت نشده'}</div>
        <input
          className={`${inp} mt-3`}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="نام نمایشی"
        />
        <button onClick={saveName} className={`${btn} mt-3`}>
          ذخیره
        </button>
      </div>
      <Loyalty coreFetch={coreFetch} storeId={storeId} notify={notify} />
      <Referral coreFetch={coreFetch} storeId={storeId} notify={notify} />
      <div className={card}>
        <h4 className="font-extrabold">اتصال تلگرام</h4>
        {link ? (
          <div className="mt-3 text-sm leading-7">
            کد: <b className="latin">{link.code}</b> (تا {Math.round(link.expires_in / 60)} دقیقه معتبر)
            {link.telegram_deeplink && (
              <a
                href={link.telegram_deeplink}
                target="_blank"
                rel="noreferrer"
                className={`${btn} mt-3 block text-center`}
              >
                باز کردن در تلگرام
              </a>
            )}
          </div>
        ) : (
          <button onClick={tg} className={`${btn} mt-3`}>
            ساخت کد اتصال
          </button>
        )}
      </div>
      <div className={card}>
        <h4 className="font-extrabold">اتصال گوگل</h4>
        {googleLinked ? (
          <div className="mt-3 text-sm font-bold text-mint">✓ حساب گوگل به این حساب متصل است</div>
        ) : (
          <>
            <p className="mt-2 text-sm leading-7 text-muted">
              با اتصال گوگل، هم با تلگرام و هم با گوگل وارد همین حساب می‌شوید.
            </p>
            <GoogleSignInButton onCredential={linkGoogle} text="continue_with" className="mt-3" />
          </>
        )}
      </div>
      <div className={card}>
        <h4 className="font-extrabold">امنیت</h4>
        <PasswordInput
          autoComplete="new-password"
          wrapClassName="mt-3"
          className={inp}
          value={pw}
          onChange={(e) => setPw(e.target.value)}
          placeholder="رمز عبور جدید"
        />
        <button disabled={pw.length < 8} onClick={setPass} className={`${btn} mt-3`}>
          تنظیم رمز
        </button>
        <div className="mt-5 border-t border-line pt-4 text-sm">
          {account?.totp_enabled ? (
            <b className="text-mint">✓ ورود دومرحله‌ای فعال است</b>
          ) : totp ? (
            <>
              <div>این کلید را در برنامه Authenticator وارد کنید:</div>
              <code dir="ltr" className="latin mt-2 block break-all rounded-xl bg-surface2 p-3 text-xs">
                {totp.secret}
              </code>
              <input
                dir="ltr"
                className={`${inp} mt-3`}
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder="کد ۶ رقمی"
              />
              <button disabled={!code} onClick={enable2fa} className={`${btn} mt-3`}>
                فعال‌سازی
              </button>
            </>
          ) : (
            <button onClick={setup2fa} className={btn}>
              راه‌اندازی ورود دومرحله‌ای
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default function Dashboard({ coreFetch, storeId, account, wallet, orders, reload, notify, onLogout }) {
  const [tab, setTab] = useState('orders');
  const [unread, setUnread] = useState(0);
  useEffect(() => {
    coreFetch(`/api/v1/stores/${storeId}/notifications?unread_only=true&limit=1`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setUnread(d.unread))
      .catch(() => {});
  }, [coreFetch, storeId]);
  const name = account?.display_name || account?.email || 'کاربر';
  const stats = [
    ['موجودی کیف پول', wallet ? `${fa(wallet.balance)} ${wallet.currency || ''}` : '—', WalletIcon, 'tab:wallet'],
    ['سفارش‌ها', fa(orders.length), Package, 'tab:orders'],
    ['اعلان خوانده‌نشده', fa(unread), Bell, 'tab:notifications'],
  ];
  return (
    <div className="mx-auto max-w-6xl px-5 py-10">
      <PageTitle eyebrow="حساب من" title={`سلام، ${name}`}>
        <a href="#/reseller" className="btn-soft btn-pill !py-2.5">
          <Store size={16} />
          پنل نماینده
        </a>
        <a href="#/" className="btn-soft btn-pill !py-2.5">
          <ArrowRight size={16} />
          صفحه اصلی
        </a>
        <button onClick={onLogout} className="btn btn-pill bg-danger-soft !py-2.5 text-danger hover:brightness-95">
          <LogOut size={16} />
          خروج
        </button>
      </PageTitle>
      <div className="mb-8 grid grid-cols-2 gap-4 sm:grid-cols-3">
        {stats.map(([l, v, Icon, k], i) => (
          <button
            key={l}
            onClick={() => setTab(k.slice(4))}
            className={`card text-right transition hover:-translate-y-0.5 hover:shadow-lift ${i === 0 ? 'col-span-2 !border-0 bg-hero !text-white sm:col-span-1' : ''}`}
          >
            <div className="flex items-center justify-between">
              <span className={`text-sm ${i === 0 ? 'text-white/60' : 'text-muted'}`}>{l}</span>
              <Icon size={18} className={i === 0 ? 'text-[#f7c85c]' : 'text-coral'} />
            </div>
            <div className="mt-3 text-2xl font-black">{v}</div>
          </button>
        ))}
      </div>
      <div className="grid gap-8 md:grid-cols-[220px_1fr]">
        <nav
          aria-label="بخش‌های حساب"
          className="-mx-5 flex gap-2 overflow-x-auto px-5 pb-1 md:sticky md:top-24 md:mx-0 md:h-fit md:flex-col md:gap-1 md:overflow-visible md:px-0"
        >
          {tabs.map(([k, l, Icon]) => (
            <button
              key={k}
              onClick={() => setTab(k)}
              aria-current={tab === k}
              className={`flex shrink-0 items-center gap-2.5 whitespace-nowrap rounded-xl px-4 py-3 text-sm font-bold transition ${tab === k ? 'bg-primary text-onprimary shadow-soft' : 'text-muted hover:bg-surface2 hover:text-ink'}`}
            >
              <Icon size={18} />
              {l}
              {k === 'notifications' && unread > 0 && (
                <span className="mr-auto rounded-full bg-coral px-2 py-0.5 text-[10px] text-onprimary">
                  {fa(unread)}
                </span>
              )}
            </button>
          ))}
        </nav>
        <section aria-live="polite" className="min-w-0">
          {tab === 'notifications' && (
            <Notifications coreFetch={coreFetch} storeId={storeId} notify={notify} onCount={setUnread} />
          )}
          {tab === 'orders' && <Orders orders={orders} />}
          {tab === 'vpn' && <Vpn coreFetch={coreFetch} storeId={storeId} notify={notify} reload={reload} />}
          {tab === 'wallet' && (
            <Wallet coreFetch={coreFetch} storeId={storeId} wallet={wallet} reload={reload} notify={notify} />
          )}
          {tab === 'profile' && (
            <Profile coreFetch={coreFetch} storeId={storeId} account={account} notify={notify} reload={reload} />
          )}
          {tab === 'tickets' && <Tickets coreFetch={coreFetch} storeId={storeId} notify={notify} />}
        </section>
      </div>
    </div>
  );
}

export function Faq() {
  const items = [
    [
      'چطور سرویس را فعال کنم؟',
      'پس از ورود و شارژ کیف پول، سرویس را انتخاب و پرداخت کنید؛ لینک اشتراک در بخش «اکانت‌های VPN» نمایش داده می‌شود.',
    ],
    [
      'پرداخت چگونه است؟',
      'خرید همیشه از کیف پول انجام می‌شود. کیف پول را با کارت‌به‌کارت (همراه رسید) یا درگاه شارژ کنید.',
    ],
    ['تمدید یا استرداد چطور است؟', 'برای تمدید یا مشکل در سفارش، از بخش تیکت‌ها با پشتیبانی در تماس باشید.'],
    [
      'قوانین استفاده',
      'استفاده غیرقانونی یا فروش مجدد بدون همکاری رسمی مجاز نیست؛ سرویس تست محدود به یک‌بار برای هر کاربر است.',
    ],
  ];
  return (
    <section id="faq" className="mx-auto max-w-3xl px-5 pb-28">
      <div className="eyebrow text-center">سوالات</div>
      <h2 className="mt-3 text-center text-4xl font-black">پرسش‌های پرتکرار</h2>
      <div className="mt-10 space-y-3">
        {items.map(([q, a]) => (
          <details key={q} className="card group !p-0 transition open:shadow-lift">
            <summary className="flex cursor-pointer items-center justify-between gap-4 p-5 font-extrabold">
              {q}
              <ChevronDown size={20} className="chev shrink-0 text-muted transition-transform" />
            </summary>
            <p className="px-5 pb-5 leading-8 text-muted">{a}</p>
          </details>
        ))}
      </div>
    </section>
  );
}
