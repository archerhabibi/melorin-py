import { downloadOrders } from './AdminSession.tsx';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Bell, CircleAlert, Download, Menu, RefreshCw, Search, Moon, X } from 'lucide-react';
import { AdminSectionView } from './AdminSections.tsx';
import { DialogHost, ThemeButton, label } from './ui.tsx';
import { Palette } from './palette.tsx';
import { legacyHash } from './infra.tsx';
import { sectionAllowed } from './adminAccess.ts';
import { toggleTheme } from './theme.ts';
import type { Json } from './types.ts';
import { flat } from './adminNav.ts';
import { fromHash } from './adminNav.ts';
import { Clock } from './AdminShell.tsx';
import { todayLabel } from './AdminShell.tsx';
import { Brand } from './AdminShell.tsx';
import { UserMenu } from './AdminShell.tsx';
import { MobileNav } from './AdminShell.tsx';
import Dashboard from './Dashboard.tsx';
import { useCore } from './AdminSession.tsx';
import { Nav } from './AdminNavigation.tsx';

export default function App({ onLogout }: { onLogout?: Json }) {
  const [section, setSection] = useState(fromHash);
  const [open, setOpen] = useState(false);
  const [notice, setNotice] = useState('');
  const [pal, setPal] = useState(false);
  const api = useCore();
  const openTickets = api.summary?.open_tickets || 0;
  // Stable identity: views list `toast` in their effect/callback dependencies, so a new function on every render re-ran their loads
  // (each toast re-rendered the app, which re-fetched, which toasted again).
  const toastTimer = useRef<Json>(null);
  const toast = useCallback((x: Json) => {
    setNotice(x);
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setNotice(''), 2600);
  }, []);
  const go = (name: Json) => {
    window.location.hash = `/${flat.find((x) => x[0] === name)![2]}`;
    setOpen(false);
  };
  useEffect(() => {
    const f = () => {
      const moved = legacyHash(window.location.hash);
      if (moved) {
        window.location.replace(moved);
        return;
      }
      setSection(fromHash());
    };
    window.addEventListener('hashchange', f);
    return () => window.removeEventListener('hashchange', f);
  }, []);
  useEffect(() => {
    const f = (e: Json) => e.key === 'Escape' && setOpen(false);
    window.addEventListener('keydown', f);
    return () => window.removeEventListener('keydown', f);
  }, []);
  useEffect(() => {
    const f = (e: Json) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPal((x) => !x);
      }
    };
    window.addEventListener('keydown', f);
    return () => window.removeEventListener('keydown', f);
  }, []);
  // A role that may not open the current screen (a bookmark, an old hash) lands on the first screen it may open.
  useEffect(() => {
    if (api.perms === undefined || sectionAllowed(api.perms, section)) return;
    const first = flat.find(([name]) => sectionAllowed(api.perms, name));
    if (first) window.location.hash = `/${first[2]}`;
  }, [api.perms, section]);
  useEffect(() => {
    document.title = `${section} · ملورین`;
    window.scrollTo(0, 0);
  }, [section]);
  const palItems = [
    ...flat
      .filter(([name]) => sectionAllowed(api.perms, name))
      .map(([name, Icon]) => ({ name, hint: 'برو به بخش', Icon, run: () => go(name) })),
    {
      name: 'به‌روزرسانی داده‌ها',
      hint: 'عملیات',
      Icon: RefreshCw,
      run: () => {
        api.refresh();
        toast('داده‌ها از Core دوباره دریافت شد');
      },
    },
    {
      name: 'خروجی CSV سفارش‌ها',
      hint: 'عملیات',
      Icon: Download,
      run: () => downloadOrders(api.base || '').catch(() => toast('دریافت خروجی ناموفق بود')),
    },
    { name: 'تغییر پوسته روشن/تاریک', hint: 'عملیات', Icon: Moon, run: toggleTheme },
  ];
  return (
    <div dir="rtl" className="min-h-screen">
      <aside className="fixed inset-y-0 right-0 z-20 hidden w-64 flex-col bg-[var(--nav)] lg:flex">
        <Brand />
        <div className="flex-1 overflow-y-auto pt-3">
          <Nav
            section={section}
            go={go}
            openTickets={openTickets}
            pendingApps={api.pendingApps}
            pendingPanelReq={api.pendingPanelReq}
            manualTasks={api.manualTasks}
            perms={api.perms}
          />
        </div>
        <div className="m-4 rounded-2xl bg-white/[.07] p-4">
          <div className={`flex items-center gap-2 text-xs ${api.health ? 'text-[#8ce0ba]' : 'text-[#f4c95d]'}`}>
            <span className="h-2 w-2 rounded-full bg-current" />
            Core API {api.health ? 'پایدار' : 'در انتظار'}
          </div>
        </div>
      </aside>
      <div className="lg:mr-64">
        <header className="sticky top-0 z-10 flex h-[72px] items-center justify-between border-b border-[var(--ln)] bg-[var(--bg)]/85 px-5 backdrop-blur-sm md:px-9">
          <div className="flex min-w-0 items-center gap-3">
            <button aria-label="باز کردن منو" className="btn btn-g lg:hidden" onClick={() => setOpen(true)}>
              <Menu size={20} />
            </button>
            <div className="min-w-0">
              <div className="hidden truncate text-xs text-[var(--mu)] sm:block">
                {todayLabel()} <span aria-hidden="true">·</span> <Clock />
              </div>
              <h1 className="truncate text-lg font-extrabold">{section}</h1>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
            <button
              aria-label="به‌روزرسانی داده‌ها"
              title="به‌روزرسانی"
              onClick={() => {
                api.refresh();
                toast('داده‌ها از Core دوباره دریافت شد');
              }}
              className="btn btn-g max-sm:!hidden"
            >
              <RefreshCw size={17} className={api.loading ? 'animate-spin' : ''} />
            </button>
            <button
              onClick={() => setPal(true)}
              aria-label="جستجوی سریع"
              className="btn btn-g gap-2 text-[var(--mu)] max-md:!hidden"
            >
              <Search size={15} />
              جستجو
              <kbd className="rounded-sm bg-[var(--mb)] px-1.5 text-[10px]" dir="ltr">
                Ctrl K
              </kbd>
            </button>
            <ThemeButton />
            <button
              aria-label="تیکت‌های باز"
              title="تیکت‌های باز"
              onClick={() => go('تیکت‌ها')}
              className="btn btn-g relative"
            >
              <Bell size={17} />
              {openTickets > 0 && <span className="absolute -left-1 -top-1 h-2.5 w-2.5 rounded-full bg-[#e8743b]" />}
            </button>
            <button
              onClick={() => downloadOrders(api.base || '').catch(() => toast('دریافت خروجی ناموفق بود'))}
              className="btn max-sm:!hidden"
            >
              <Download size={16} />
              خروجی سفارش‌ها
            </button>
            <UserMenu base={api.base} go={go} toast={toast} onLogout={onLogout} adminMe={api.me} />
          </div>
        </header>
        <main className="p-5 md:p-9">
          <div className="mx-auto max-w-7xl">
            {Array.isArray(api.perms) && api.perms.length === 0 && !api.loading && (
              <div role="alert" className="mb-5 rounded-2xl bg-[var(--wnb)] p-4 text-sm font-bold text-[var(--wn)]">
                برای حساب شما نقشی تعریف نشده است. از مالک پنل بخواهید نقش مناسبی به شما بدهد.
              </div>
            )}
            {api.error && (
              <div
                role="alert"
                className="mb-5 flex items-center gap-3 rounded-2xl bg-[var(--bdb)] p-4 text-sm font-bold text-[var(--bd)]"
              >
                <CircleAlert size={18} />
                {api.error}
              </div>
            )}
            {section !== 'داشبورد' && (
              <div className="mb-7">
                <AdminSectionView section={section} api={api} toast={toast} />
              </div>
            )}
            {section === 'داشبورد' && <Dashboard api={api} toast={toast} />}
          </div>
        </main>
      </div>
      {open && (
        <MobileNav onClose={() => setOpen(false)}>
          <div className="flex items-center justify-between">
            <Brand />
            <button aria-label="بستن منو" onClick={() => setOpen(false)} className="ml-4 rounded-lg p-2 text-white">
              <X size={22} />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto">
            <Nav
              section={section}
              go={go}
              openTickets={openTickets}
              pendingApps={api.pendingApps}
              pendingPanelReq={api.pendingPanelReq}
              manualTasks={api.manualTasks}
              perms={api.perms}
            />
          </div>
        </MobileNav>
      )}
      {pal && <Palette items={palItems} onClose={() => setPal(false)} />}
      <DialogHost />
      <div aria-live="polite" className="pointer-events-none fixed bottom-6 left-1/2 z-40 -translate-x-1/2">
        {notice && (
          <div className="rise rounded-full bg-[var(--nav)] px-5 py-3 text-sm font-bold text-white shadow-xl ring-1 ring-white/10">
            {notice}
          </div>
        )}
      </div>
    </div>
  );
}
