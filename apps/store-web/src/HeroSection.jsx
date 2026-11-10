// Landing hero (split out of App.jsx, T-R11).
import { ArrowLeft, Check } from 'lucide-react';
import { HeroVisual } from './landing.jsx';

export function HeroSection() {
  return (
    <section className="hero-bg relative overflow-hidden">
      <div className="grid-dots absolute inset-0" />
      <div className="relative mx-auto grid max-w-6xl gap-14 px-5 pb-24 pt-14 md:grid-cols-[1.1fr_.9fr] md:items-center md:pt-20">
        <div className="anim-rise">
          <div className="inline-flex items-center gap-2 rounded-full bg-mint-soft px-4 py-2 text-xs font-extrabold text-mint">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-mint opacity-60" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-mint" />
            </span>
            شبکه پایدار، بدون پیچیدگی
          </div>
          <h1 className="mt-6 text-[2.6rem] font-black leading-[1.18] tracking-tight sm:text-6xl md:text-7xl">
            اینترنتت را{' '}
            <span className="relative whitespace-nowrap text-coral">
              آزادتر
              <svg
                aria-hidden="true"
                viewBox="0 0 220 12"
                className="absolute -bottom-2 right-0 h-3 w-full text-accent"
                preserveAspectRatio="none"
              >
                <path
                  d="M2 8c40-7 90-7 216-1"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="5"
                  strokeLinecap="round"
                />
              </svg>
            </span>
            <br />
            انتخاب کن.
          </h1>
          <p className="mt-7 max-w-lg text-lg leading-9 text-muted">
            سرویس VPN ساده، سریع و قابل تمدید. قیمت‌گذاری شفاف، کیف پول امن و پشتیبانی واقعی، همه در یک جا.
          </p>
          <div className="mt-9 flex flex-wrap gap-3">
            <a href="#plans" className="btn-primary btn-pill !px-8 !py-4">
              دیدن سرویس‌ها <ArrowLeft size={18} />
            </a>
            <a href="#how" className="btn-soft btn-pill !px-8 !py-4">
              چطور کار می‌کند؟
            </a>
          </div>
          <ul className="mt-10 flex flex-wrap gap-x-7 gap-y-3 text-sm font-semibold text-muted">
            {['تحویل خودکار', 'پرداخت با کیف پول', 'پشتیبانی تیکتی'].map((t) => (
              <li key={t} className="flex items-center gap-2">
                <span className="grid h-5 w-5 place-items-center rounded-full bg-mint-soft text-mint">
                  <Check size={13} strokeWidth={3} />
                </span>
                {t}
              </li>
            ))}
          </ul>
        </div>
        <div className="anim-rise [animation-delay:.15s]">
          <HeroVisual />
        </div>
      </div>
    </section>
  );
}
