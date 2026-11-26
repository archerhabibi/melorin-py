// Static "how it works" and "why this store" sections (split out of App.jsx, T-R11).
import type { Json } from './types';
import { ChevronDown } from 'lucide-react';
import { STEPS, WHY } from './landing.tsx';
import { useStoreBrand } from './storeBrand.tsx';

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
  const { name } = useStoreBrand();
  return (
    <section id="why" className="mx-auto max-w-6xl px-5 pb-24">
      <div className="grid gap-10 lg:grid-cols-[.8fr_1.2fr]">
        <div>
          <div className="eyebrow">چرا {name}؟</div>
          <h2 className="mt-3 text-4xl font-black leading-tight">
            کمتر تنظیم کن.
            <br />
            بیشتر وصل باش.
          </h2>
          <p className="mt-5 max-w-sm leading-8 text-muted">
            {name} برای کسی ساخته شده که فقط می‌خواهد سرویسش کار کند، بدون پیچیدگی و بدون غافلگیری در صورتحساب.
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
