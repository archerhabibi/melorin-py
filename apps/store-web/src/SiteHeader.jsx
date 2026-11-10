// Sticky top bar + collapsible mobile menu (split out of App.jsx, T-R11).
import { Menu, User, X } from 'lucide-react';
import { ThemeToggle } from './ui.jsx';
import { Logo, NAV } from './landing.jsx';

export function SiteHeader({ inApp, goAccount, account, accessToken, menu, setMenu }) {
  return (
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
  );
}
