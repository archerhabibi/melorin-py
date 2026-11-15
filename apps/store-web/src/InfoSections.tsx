// Static "how it works" and "why Melorin" sections (split out of App.jsx, T-R11).
import type { Json } from './types';
import { STEPS, WHY } from './landing.tsx';

export function HowSection() {
  return (
    <section id="how" className="mx-auto max-w-6xl px-5 py-24">
      <div className="eyebrow">نحوه خرید</div>
      <h2 className="mt-3 max-w-xl text-4xl font-black leading-tight">چهار قدم تا اتصال.</h2>
      <ol className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
        {STEPS.map(([Icon, t, d]: Json, i: number) => (
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
  );
}

export function WhySection() {
  return (
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
          {WHY.map(([Icon, t, d]: Json) => (
            <div key={t} className="card !p-6 transition hover:shadow-lift">
              <Icon className="text-coral" size={26} strokeWidth={1.8} />
              <h3 className="mt-6 text-lg font-extrabold">{t}</h3>
              <p className="mt-2 text-sm leading-7 text-muted">{d}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/** Docs/25 section 8.2: a visible entry point on the landing page; opens the dashboard on the linking tab. */
export const LINKING_TAB_KEY = 'melorin.dashboard.tab';

export function LinkAccountsSection({ goAccount }: { goAccount?: Json }) {
  const open = () => {
    try {
      sessionStorage.setItem(LINKING_TAB_KEY, 'linking');
    } catch {
      /* storage blocked: the user simply lands on the default tab */
    }
    goAccount?.();
  };
  return (
    <section id="link-accounts" className="mx-auto max-w-6xl px-5 pb-24">
      <div className="card flex flex-wrap items-center justify-between gap-5 !p-8">
        <div className="max-w-xl">
          <h2 className="text-2xl font-black">همه حساب‌هایت را یکپارچه کن</h2>
          <p className="mt-3 leading-8 text-muted">
            حساب تلگرام، Google و ایمیل خود را به یک پروفایل متصل کن و از یک کیف پول و تاریخچه سفارش مشترک استفاده کن.
          </p>
        </div>
        <button onClick={open} className="btn-primary btn-pill !px-8 !py-4">
          اتصال حساب‌های من
        </button>
      </div>
    </section>
  );
}
