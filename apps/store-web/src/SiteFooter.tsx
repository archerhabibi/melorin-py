// Site footer (split out of App.jsx, T-R11).
import { Logo, NAV } from './landing.tsx';
import type { Json } from './types';

export function SiteFooter({ inApp, goAccount, accessToken }: { inApp?: Json; goAccount?: Json; accessToken?: Json }) {
  return (
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
  );
}
