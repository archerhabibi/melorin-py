// Fixed bottom navigation on small screens (split out of App.jsx, T-R11).
import { Home, LayoutGrid, LifeBuoy, User } from 'lucide-react';
import type { Json } from './types';

export function MobileNav({ inApp, goAccount }: { inApp?: Json; goAccount?: Json }) {
  return (
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
  );
}
