// Melorin Admin Web — every KPI, row and action comes from the authenticated Core API.
// Tokens live only in memory (see auth.js); nothing is persisted in browser storage.
import { useCallback, useEffect, useState } from 'react';
import { AdminSectionView } from './AdminSections.jsx';
import { API_BASE, authFetch, getJson } from './api.js';
import { clearTokens } from './auth.js';
import Trend from './Trend.jsx';
import { Badge, DialogHost, ThemeButton, confirmDialog, label, sid, tone } from './ui.jsx';
import { Palette } from './palette.jsx';
import { toggleTheme } from './theme.js';
import { Activity, Bell, CircleAlert, CreditCard, Database, Download, Fingerprint, LayoutDashboard, Menu, Package, PanelTop, Percent, RefreshCw, Server, Settings, ShieldCheck, Ticket, Users, WalletCards, X, Boxes, ScrollText, Store, Search, Moon, LogOut, KeyRound, ChevronDown, UserRound } from 'lucide-react';

// Section keys are Persian labels (AdminSections/AdminExtra route on them); slug drives the URL hash.
const groups = [
  ['نمای کلی', [['داشبورد', LayoutDashboard, 'home']]],
  ['عملیات', [['سفارش‌ها', Package, 'orders'], ['پرداخت‌ها', CreditCard, 'payments'], ['اکانت‌های VPN', Server, 'vpn'], ['تیکت‌ها', Ticket, 'tickets']]],
  ['فروش و مشتریان', [['کاربران', Users, 'users'], ['فروشگاه‌ها', Store, 'stores'], ['محصولات', Boxes, 'products'], ['کوپن‌ها', Percent, 'coupons']]],
  ['زیرساخت و سیستم', [['پنل‌ها', PanelTop, 'panels'], ['تنظیمات', Settings, 'settings'], ['ممیزی', ScrollText, 'audit'], ['بررسی هویت', Fingerprint, 'identity']]],
];
const flat = groups.flatMap(([, items]) => items);
const fromHash = () => (flat.find((x) => `#/${x[2]}` === window.location.hash) || flat[0])[0];

const todayLabel = () => new Intl.DateTimeFormat('fa-IR-u-ca-persian', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }).format(new Date());
const money = (v) => new Intl.NumberFormat('fa-IR').format(v || 0);
const moneyByCurrency = (rows) => (rows || []).map((x) => `${money(x.amount)} ${x.currency}`).join(' · ') || '۰';

function useCore() {
  const base = API_BASE;
  const [data, setData] = useState({ summary: null, orders: [], users: [], tickets: [], stores: [], health: null, backups: [], loading: true, error: '' });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    setData((x) => ({ ...x, loading: true }));
    (async () => {
      try {
        const [summary, orders, health, backups, users, tickets, stores] = await Promise.all([
          '/api/v1/admin/reports/summary', '/api/v1/admin/orders', '/api/v1/admin/health', '/api/v1/admin/operations/backups', '/api/v1/admin/users', '/api/v1/admin/tickets', '/api/v1/admin/stores',
        ].map((p) => getJson(base, p)));
        if (live) setData({ summary, orders, health, backups, users, tickets, stores, loading: false, error: '' });
      } catch (e) {
        if (live) setData((x) => ({ ...x, loading: false, error: 'اتصال به Core API برقرار نشد. وارد شوید یا آدرس API را بررسی کنید.' }));
      }
    })();
    return () => { live = false; };
  }, [base, tick]);
  const refresh = useCallback(() => setTick((x) => x + 1), []);
  return { ...data, base, refresh, tick };
}

async function downloadOrders(base) {
  const r = await authFetch(base, '/api/v1/admin/reports/orders.csv');
  if (!r.ok) throw Error(`export ${r.status}`);
  const blob = await r.blob(), url = URL.createObjectURL(blob), a = document.createElement('a');
  a.href = url; a.download = 'melorin-orders.csv'; a.click(); URL.revokeObjectURL(url);
}
async function refundPayment(base, paymentId, reason) {
  const r = await authFetch(base, `/api/v1/admin/payments/${paymentId}/refund`, { method: 'POST', body: JSON.stringify({ reason }) });
  if (!r.ok) throw Error(`refund ${r.status}`);
  return r.json();
}

function Nav({ section, go, openTickets }) {
  return <nav aria-label="منوی اصلی" className="space-y-5 px-3 pb-6">{groups.map(([g, items]) => <div key={g}><div className="mb-1.5 px-3 text-[11px] font-bold tracking-wide text-white/35">{g}</div>{items.map(([name, Icon]) => <button key={name} onClick={() => go(name)} aria-current={section === name ? 'page' : undefined} className={`navb ${section === name ? 'on' : ''}`}><Icon size={18} /><span>{name}</span>{name === 'تیکت‌ها' && openTickets > 0 && <span className="mr-auto rounded-full bg-[#e8743b] px-2 py-0.5 text-[10px] font-bold text-white">{openTickets}</span>}</button>)}</div>)}</nav>;
}

function Brand() {
  return <div className="flex h-[72px] items-center gap-3 px-6"><div className="grid h-10 w-10 place-items-center rounded-2xl bg-[#f4c95d] text-xl font-extrabold text-[#0f1f38]">م</div><div><div className="font-extrabold text-white">ملورین</div><div className="text-[10px] tracking-[.2em] text-white/50">CONTROL ROOM</div></div></div>;
}

const Kpi = ({ t, n, s, I, tint, loading }) => <div className="card rise p-5"><div className="flex items-start justify-between"><div className="text-sm text-[var(--mu)]">{t}</div><div className={`rounded-xl p-2.5 ${tint}`}><I size={17} /></div></div>{loading ? <div className="skel mt-5 h-8 w-2/3" /> : <div className="mt-5 text-2xl font-extrabold tracking-tight">{n}</div>}<div className="mt-2 text-xs font-semibold text-[var(--mu)]">{s}</div></div>;

function Dashboard({ api, toast }) {
  const summary = api.summary || {};
  const byStatus = [...(summary.orders || [])].sort((a, b) => b.count - a.count);
  const orderCount = byStatus.reduce((a, x) => a + x.count, 0);
  const active = byStatus.filter((x) => ['paid', 'processing', 'provisioning'].includes(x.status)).reduce((a, x) => a + x.count, 0);
  const needsAttention = byStatus.filter((x) => ['manual_review', 'provisioning_failed', 'payment_failed', 'refund_pending'].includes(x.status)).reduce((a, x) => a + x.count, 0);
  const openTickets = summary.open_tickets || 0;
  const h = api.health, ok = (k) => h?.[k] === 'ok';
  const services = [['Core API', ok('api')], ['PostgreSQL', ok('database')], ['Redis', ok('redis')], ['Worker', ok('worker')]];
  const rows = api.orders || [];
  return <div className="space-y-6">
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <Kpi loading={api.loading} t="فروش ثبت‌شده" n={moneyByCurrency(summary.payments)} s="از گزارش مالی Core" I={WalletCards} tint="bg-[var(--okb)] text-[var(--ok)]" />
      <Kpi loading={api.loading} t="سفارش‌های فعال" n={money(active)} s={`${money(orderCount)} کل سفارش`} I={Package} tint="bg-[var(--inb)] text-[var(--in)]" />
      <Kpi loading={api.loading} t="نیازمند توجه" n={money(needsAttention)} s="بررسی دستی، خطا یا استرداد" I={CircleAlert} tint="bg-[var(--wnb)] text-[var(--wn)]" />
      <Kpi loading={api.loading} t="تیکت‌های باز" n={money(openTickets)} s="از صف پشتیبانی" I={Ticket} tint="bg-[var(--mb)] text-[var(--tx)]" />
    </div>
    <div className="grid gap-6 xl:grid-cols-[1.6fr_.9fr]">
      <div className="space-y-6">
        <Trend tick={api.tick} />
        <section className="card rise p-5"><div className="flex items-center justify-between"><h3 className="font-extrabold">توزیع وضعیت سفارش‌ها</h3><span className="text-xs text-[var(--mu)]">{money(orderCount)} سفارش</span></div>
          {orderCount ? <><div className="mt-4 flex h-3 overflow-hidden rounded-full bg-[var(--mb)]" role="img" aria-label="نمودار توزیع وضعیت سفارش‌ها">{byStatus.map((x) => <div key={x.status} title={`${label(x.status)}: ${x.count}`} style={{ width: `${(x.count / orderCount) * 100}%`, background: `var(--${tone(x.status)})` }} />)}</div>
            <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2">{byStatus.map((x) => <div key={x.status} className="flex items-center gap-2 text-xs"><Badge s={x.status} /><b>{money(x.count)}</b></div>)}</div></> : <p className="mt-4 text-sm text-[var(--mu)]">{api.loading ? 'در حال دریافت…' : 'هنوز سفارشی ثبت نشده'}</p>}
        </section>
        <section className="card rise overflow-hidden"><div className="flex items-center justify-between border-b border-[var(--ln)] px-5 py-4"><div><h3 className="font-extrabold">آخرین سفارش‌ها</h3><p className="mt-1 text-xs text-[var(--mu)]">دریافت مستقیم از Core API</p></div><button onClick={api.refresh} className="text-sm font-bold text-[var(--ac)]">به‌روزرسانی</button></div>
          <div className="overflow-x-auto"><table className="tbl min-w-[620px]"><thead><tr><th>شماره</th><th>Store</th><th>مبلغ</th><th>وضعیت</th><th>شناسه</th><th>عملیات</th></tr></thead><tbody>{rows.length ? rows.slice(0, 8).map((o) => <tr key={String(o.id)}><td className="font-bold">{o.number}</td><td className="text-[var(--mu)]">{sid(o.store_id)}</td><td className="font-semibold">{money(o.total)} {o.currency}</td><td><Badge s={o.status} /></td><td className="text-xs text-[var(--mu)]">{sid(o.id)}</td><td><button disabled={!o.payment_id || o.payment_status !== 'succeeded'} onClick={async () => { if (!(await confirmDialog('استرداد واقعی این پرداخت انجام شود؟', { title: 'استرداد پرداخت', danger: true, ok: 'استرداد' }))) return; refundPayment(api.base || '', o.payment_id, 'درخواست استرداد توسط Admin').then(() => { toast('استرداد ثبت شد'); api.refresh(); }).catch(() => toast('استرداد ناموفق بود')); }} className="btn btn-g btn-d">استرداد</button></td></tr>) : <tr><td colSpan="6" className="p-12 text-center text-sm text-[var(--mu)]">{api.loading ? 'در حال دریافت…' : 'سفارشی از API برنگشت'}</td></tr>}</tbody></table></div></section>
      </div>
      <aside className="space-y-6">
        <section className="rise rounded-2xl bg-[var(--nav)] p-5 text-white"><div className="flex items-center justify-between"><h3 className="font-extrabold">سلامت زیرساخت</h3><ShieldCheck className="text-[#8ce0ba]" size={20} /></div>
          <div className="mt-5 space-y-3.5">{services.map(([n, good]) => <div key={n} className="flex items-center justify-between border-b border-white/10 pb-3 last:border-0 last:pb-0"><div className="flex items-center gap-2 text-sm"><span className={`h-2 w-2 rounded-full ${good ? 'bg-[#8ce0ba]' : h ? 'bg-[#f87171]' : 'bg-[#f4c95d]'}`} />{n}</div><div className="text-xs text-white/70">{good ? 'پایدار' : h ? 'مشکل‌دار' : 'نامشخص'}</div></div>)}</div></section>
        <section className="card rise p-5"><div className="flex items-center justify-between"><h3 className="font-extrabold">آخرین Backup</h3><Database size={19} className="text-[var(--ac)]" /></div>
          {api.backups?.[0] ? <div className="mt-4 space-y-2 text-sm"><Badge s={api.backups[0].status} /><div className="text-xs text-[var(--mu)]">{new Date(api.backups[0].created_at).toLocaleString('fa-IR')}</div><div className="text-xs text-[var(--mu)]">{money(api.backups.length)} اجرا ثبت شده</div></div> : <p className="mt-4 text-sm text-[var(--mu)]">{api.loading ? 'در حال دریافت…' : 'هنوز Backup ثبت نشده'}</p>}</section>
      </aside>
    </div>
  </div>;
}

// Signed-in admin identity (GET /api/v1/me) + sign-out (POST /api/v1/auth/logout revokes the refresh token and clears the cookie).
function UserMenu({ base, go, toast, onLogout }) {
  const [me, setMe] = useState(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => { getJson(base, '/api/v1/me').then(setMe).catch(() => {}); }, [base]);
  useEffect(() => {
    if (!open) return;
    const esc = (e) => e.key === 'Escape' && setOpen(false);
    const away = (e) => !e.target.closest?.('[data-usermenu]') && setOpen(false);
    window.addEventListener('keydown', esc); window.addEventListener('pointerdown', away);
    return () => { window.removeEventListener('keydown', esc); window.removeEventListener('pointerdown', away); };
  }, [open]);
  const name = me?.display_name || me?.email || 'مدیر';
  const initials = [...name.trim()].slice(0, 1).join('').toUpperCase();
  const signOut = async () => {
    setBusy(true);
    let ok = false;
    try { ok = (await authFetch(base, '/api/v1/auth/logout', { method: 'POST', body: '{}' })).ok; } catch { ok = false; }
    if (!ok) { setBusy(false); toast('خروج از سرور تأیید نشد؛ دوباره تلاش کنید'); return; }
    clearTokens();
    onLogout?.();
  };
  return <div className="relative" data-usermenu>
    <button onClick={() => setOpen((x) => !x)} aria-haspopup="menu" aria-expanded={open} className="btn btn-g gap-2 !py-1.5 !pl-2 !pr-1.5">
      <span className="grid h-7 w-7 place-items-center rounded-lg bg-[var(--okb)] text-xs font-extrabold text-[var(--ok)]">{initials || <UserRound size={15} />}</span>
      <span className="hidden max-w-[9rem] truncate text-xs font-bold sm:block">{name}</span><ChevronDown size={14} className="text-[var(--mu)]" />
    </button>
    {open && <div role="menu" className="card rise absolute left-0 top-[calc(100%+8px)] z-30 w-64 overflow-hidden p-1.5">
      <div className="border-b border-[var(--ln)] px-3 pb-3 pt-2"><div className="truncate text-sm font-extrabold">{name}</div>{me?.email && me.email !== name && <div dir="ltr" className="truncate text-right text-xs text-[var(--mu)]">{me.email}</div>}<div className="mt-2 flex flex-wrap gap-1.5"><span className="badge b-in">{me?.is_admin === false ? 'کاربر' : 'Super Admin'}</span>{me && <span className={`badge ${me.totp_enabled ? 'b-ok' : 'b-wn'}`}>{me.totp_enabled ? 'TOTP فعال' : 'TOTP غیرفعال'}</span>}</div></div>
      <button role="menuitem" onClick={() => { setOpen(false); go('تنظیمات'); }} className="mt-1 flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm hover:bg-[var(--mb)]"><KeyRound size={16} className="text-[var(--mu)]" />رمز عبور و امنیت</button>
      <button role="menuitem" disabled={busy} onClick={signOut} className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-bold text-[var(--bd)] hover:bg-[var(--bdb)] disabled:opacity-50"><LogOut size={16} />{busy ? 'در حال خروج…' : 'خروج از حساب'}</button>
    </div>}
  </div>;
}

export default function App({ onLogout }) {
  const [section, setSection] = useState(fromHash);
  const [open, setOpen] = useState(false);
  const [notice, setNotice] = useState('');
  const [pal, setPal] = useState(false);
  const api = useCore();
  const openTickets = api.summary?.open_tickets || 0;
  const toast = (x) => { setNotice(x); setTimeout(() => setNotice(''), 2600); };
  const go = (name) => { window.location.hash = `/${flat.find((x) => x[0] === name)[2]}`; setOpen(false); };
  useEffect(() => { const f = () => setSection(fromHash()); window.addEventListener('hashchange', f); return () => window.removeEventListener('hashchange', f); }, []);
  useEffect(() => { const f = (e) => e.key === 'Escape' && setOpen(false); window.addEventListener('keydown', f); return () => window.removeEventListener('keydown', f); }, []);
  useEffect(() => { const f = (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPal((x) => !x); } }; window.addEventListener('keydown', f); return () => window.removeEventListener('keydown', f); }, []);
  useEffect(() => { document.title = `${section} · ملورین`; window.scrollTo(0, 0); }, [section]);
  const palItems = [
    ...flat.map(([name, Icon]) => ({ name, hint: 'برو به بخش', Icon, run: () => go(name) })),
    { name: 'به‌روزرسانی داده‌ها', hint: 'عملیات', Icon: RefreshCw, run: () => { api.refresh(); toast('داده‌ها از Core دوباره دریافت شد'); } },
    { name: 'خروجی CSV سفارش‌ها', hint: 'عملیات', Icon: Download, run: () => downloadOrders(api.base || '').catch(() => toast('دریافت خروجی ناموفق بود')) },
    { name: 'تغییر پوسته روشن/تاریک', hint: 'عملیات', Icon: Moon, run: toggleTheme },
  ];
  return <div dir="rtl" className="min-h-screen">
    <aside className="fixed inset-y-0 right-0 z-20 hidden w-64 flex-col bg-[var(--nav)] lg:flex"><Brand /><div className="flex-1 overflow-y-auto pt-3"><Nav section={section} go={go} openTickets={openTickets} /></div>
      <div className="m-4 rounded-2xl bg-white/[.07] p-4"><div className={`flex items-center gap-2 text-xs ${api.health ? 'text-[#8ce0ba]' : 'text-[#f4c95d]'}`}><span className="h-2 w-2 rounded-full bg-current" />Core API {api.health ? 'پایدار' : 'در انتظار'}</div></div></aside>
    <div className="lg:mr-64">
      <header className="sticky top-0 z-10 flex h-[72px] items-center justify-between border-b border-[var(--ln)] bg-[var(--bg)]/85 px-5 backdrop-blur md:px-9">
        <div className="flex items-center gap-3"><button aria-label="باز کردن منو" className="btn btn-g lg:hidden" onClick={() => setOpen(true)}><Menu size={20} /></button><div><div className="text-xs text-[var(--mu)]">{todayLabel()}</div><h1 className="text-lg font-extrabold">{section}</h1></div></div>
        <div className="flex items-center gap-2">
          <button aria-label="به‌روزرسانی داده‌ها" title="به‌روزرسانی" onClick={() => { api.refresh(); toast('داده‌ها از Core دوباره دریافت شد'); }} className="btn btn-g"><RefreshCw size={17} className={api.loading ? 'animate-spin' : ''} /></button>
          <button onClick={() => setPal(true)} aria-label="جستجوی سریع" className="btn btn-g hidden gap-2 text-[var(--mu)] md:inline-flex"><Search size={15} />جستجو<kbd className="rounded bg-[var(--mb)] px-1.5 text-[10px]" dir="ltr">Ctrl K</kbd></button>
          <ThemeButton />
          <button aria-label="تیکت‌های باز" title="تیکت‌های باز" onClick={() => go('تیکت‌ها')} className="btn btn-g relative"><Bell size={17} />{openTickets > 0 && <span className="absolute -left-1 -top-1 h-2.5 w-2.5 rounded-full bg-[#e8743b]" />}</button>
          <button onClick={() => downloadOrders(api.base || '').catch(() => toast('دریافت خروجی ناموفق بود'))} className="btn hidden sm:inline-flex"><Download size={16} />خروجی سفارش‌ها</button>
          <UserMenu base={api.base} go={go} toast={toast} onLogout={onLogout} />
        </div>
      </header>
      <main className="p-5 md:p-9"><div className="mx-auto max-w-7xl">
        {api.error && <div role="alert" className="mb-5 flex items-center gap-3 rounded-2xl bg-[var(--bdb)] p-4 text-sm font-bold text-[var(--bd)]"><CircleAlert size={18} />{api.error}</div>}
        {section !== 'داشبورد' && <div className="mb-7"><AdminSectionView section={section} api={api} toast={toast}/></div>}
        {section === 'داشبورد' && <Dashboard api={api} toast={toast} />}
      </div></main>
    </div>
    {open && <div className="fixed inset-0 z-30 bg-black/55 lg:hidden" onClick={() => setOpen(false)}><div role="dialog" aria-modal="true" className="absolute right-0 top-0 flex h-full w-72 flex-col bg-[var(--nav)]" onClick={(e) => e.stopPropagation()}><div className="flex items-center justify-between"><Brand /><button aria-label="بستن منو" onClick={() => setOpen(false)} className="ml-4 rounded-lg p-2 text-white"><X size={22} /></button></div><div className="flex-1 overflow-y-auto"><Nav section={section} go={go} openTickets={openTickets} /></div></div></div>}
    {pal && <Palette items={palItems} onClose={() => setPal(false)} />}
    <DialogHost />
    <div aria-live="polite" className="pointer-events-none fixed bottom-6 left-1/2 z-40 -translate-x-1/2">{notice && <div className="rise rounded-full bg-[var(--nav)] px-5 py-3 text-sm font-bold text-white shadow-xl ring-1 ring-white/10">{notice}</div>}</div>
  </div>;
}
