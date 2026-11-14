import { backdropProps } from './useDialog.ts';
import type { ReactNode } from 'react';
import { useEffect, useState } from 'react';
import { LogOut, KeyRound, ChevronDown, UserRound } from 'lucide-react';
import { authFetch, getJson } from './api.ts';
import { clearTokens } from './auth.ts';
import { googleSignOut } from './GoogleSignIn.tsx';
import { label } from './ui.tsx';
import { useDialog } from './useDialog.ts';
import type { AdminMe, Json, Toast } from './types.ts';

export const todayLabel = () =>
  new Intl.DateTimeFormat('fa-IR-u-ca-persian', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  }).format(new Date());
// Live wall-clock shown next to the date (browser timezone, Persian digits).
const timeFmt = new Intl.DateTimeFormat('fa-IR', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});
export function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return (
    <time dateTime={now.toISOString()} dir="ltr" className="inline-block tabular-nums">
      {timeFmt.format(now)}
    </time>
  );
}
export function Brand() {
  return (
    <div className="flex h-[72px] items-center gap-3 px-6">
      <div className="grid h-10 w-10 place-items-center rounded-2xl bg-[#f4c95d] text-xl font-extrabold text-[#0f1f38]">
        م
      </div>
      <div>
        <div className="font-extrabold text-white">ملورین</div>
        <div className="text-[10px] tracking-[.2em] text-white/50">CONTROL ROOM</div>
      </div>
    </div>
  );
}

export function UserMenu({
  base,
  go,
  toast,
  onLogout,
  adminMe,
}: {
  base: string;
  go?: Json;
  toast: Toast;
  onLogout?: Json;
  adminMe?: AdminMe | null;
}) {
  const [me, setMe] = useState<Json>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    getJson(base, '/api/v1/me')
      .then(setMe)
      .catch(() => {});
  }, [base]);
  useEffect(() => {
    if (!open) return;
    const esc = (e: Json) => e.key === 'Escape' && setOpen(false);
    const away = (e: Json) => !e.target.closest?.('[data-usermenu]') && setOpen(false);
    window.addEventListener('keydown', esc);
    window.addEventListener('pointerdown', away);
    return () => {
      window.removeEventListener('keydown', esc);
      window.removeEventListener('pointerdown', away);
    };
  }, [open]);
  const name = me?.display_name || me?.email || 'مدیر';
  const initials = [...name.trim()].slice(0, 1).join('').toUpperCase();
  const signOut = async () => {
    setBusy(true);
    let ok = false;
    try {
      ok = (await authFetch(base, '/api/v1/auth/logout', { method: 'POST', body: '{}' })).ok;
    } catch {
      ok = false;
    }
    if (!ok) {
      setBusy(false);
      toast('خروج از سرور تأیید نشد؛ دوباره تلاش کنید');
      return;
    }
    googleSignOut();
    clearTokens();
    onLogout?.();
  };
  return (
    <div className="relative" data-usermenu>
      <button
        onClick={() => setOpen((x) => !x)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="btn btn-g gap-2 !py-1.5 !pl-2 !pr-1.5"
      >
        <span className="grid h-7 w-7 place-items-center rounded-lg bg-[var(--okb)] text-xs font-extrabold text-[var(--ok)]">
          {initials || <UserRound size={15} />}
        </span>
        <span className="hidden max-w-[9rem] truncate text-xs font-bold sm:block">{name}</span>
        <ChevronDown size={14} className="text-[var(--mu)]" />
      </button>
      {open && (
        <div role="menu" className="card rise absolute left-0 top-[calc(100%+8px)] z-30 w-64 overflow-hidden p-1.5">
          <div className="border-b border-[var(--ln)] px-3 pb-3 pt-2">
            <div className="truncate text-sm font-extrabold">{name}</div>
            {me?.email && me.email !== name && (
              <div dir="ltr" className="truncate text-right text-xs text-[var(--mu)]">
                {me.email}
              </div>
            )}
            <div className="mt-2 flex flex-wrap gap-1.5">
              <span className="badge b-in">{adminMe?.role_label || (me?.is_admin === false ? 'کاربر' : 'ادمین')}</span>
              {me && (
                <span className={`badge ${me.totp_enabled ? 'b-ok' : 'b-wn'}`}>
                  {me.totp_enabled ? 'TOTP فعال' : 'TOTP غیرفعال'}
                </span>
              )}
            </div>
          </div>
          <button
            role="menuitem"
            onClick={() => {
              setOpen(false);
              go('حساب من');
            }}
            className="mt-1 flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm hover:bg-[var(--mb)]"
          >
            <KeyRound size={16} className="text-[var(--mu)]" />
            رمز عبور و امنیت
          </button>
          <button
            role="menuitem"
            disabled={busy}
            onClick={signOut}
            className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-bold text-[var(--bd)] hover:bg-[var(--bdb)] disabled:opacity-50"
          >
            <LogOut size={16} />
            {busy ? 'در حال خروج…' : 'خروج از حساب'}
          </button>
        </div>
      )}
    </div>
  );
}

export function MobileNav({ onClose, children }: { onClose?: Json; children?: ReactNode }) {
  const ref = useDialog(onClose);
  return (
    <div className="fixed inset-0 z-30 bg-black/55 lg:hidden" {...backdropProps(onClose)}>
      <div
        ref={ref}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label="منوی اصلی"
        className="absolute right-0 top-0 flex h-full w-72 flex-col bg-[var(--nav)]"
      >
        {children}
      </div>
    </div>
  );
}
