// Static landing-page pieces split out of App.jsx (T-R11/T-W14): copy, constants and presentational components only.
import { KeyRound, LayoutGrid, LifeBuoy, Link2, Send, ShieldCheck, Wallet as WalletIcon, Zap } from 'lucide-react';
import type { Json } from './types';

export const NAV = [
  ['#plans', 'سرویس‌ها'],
  ['#how', 'نحوه خرید'],
  ['#why', 'چرا ملورین؟'],
  ['#faq', 'سوالات'],
];
export const STEPS = [
  [Send, 'ورود با تلگرام یا ایمیل', 'با یک تأیید در ربات تلگرام یا با کد ایمیل؛ بدون رمز عبور.'],
  [WalletIcon, 'شارژ کیف پول', 'کارت‌به‌کارت با رسید یا درگاه آنلاین.'],
  [LayoutGrid, 'انتخاب سرویس', 'پیش‌فاکتور شفاف را ببین و پرداخت کن.'],
  [Link2, 'دریافت لینک', 'لینک اشتراک بلافاصله در حسابت آماده است.'],
];
export const NAME_RE = /^[A-Za-z0-9_-]{3,}$/;
export async function errOf(r: Json, fallback: Json) {
  try {
    const d = await r.json();
    return d?.error?.message || (typeof d?.detail === 'string' ? d.detail : '') || fallback;
  } catch {
    return fallback;
  }
}
export const WHY = [
  [WalletIcon, 'کیف پول شفاف', 'شارژ، خرید و تمدید را در یک گردش مالی ساده ببین؛ هر تراکنش ردیف مشخصی دارد.'],
  [LifeBuoy, 'پشتیبانی انسانی', 'اگر جایی گیر کردی، از بخش تیکت‌ها پیام بده و پاسخ همان‌جا بیاید.'],
  [ShieldCheck, 'امنیت حساب', 'ورود با تأیید در تلگرام یا کد ایمیل، امکان ورود دومرحله‌ای و مدیریت رمز عبور.'],
  [KeyRound, 'بدون قفل شدن', 'سرویس و اطلاعاتت مال خودت است، نه یک پنل مبهم.'],
];

export function Logo() {
  return (
    <a href="#/" className="flex items-center gap-3" aria-label="ملورین؛ صفحه اصلی">
      <span className="grid h-10 w-10 place-items-center rounded-2xl bg-hero text-xl font-extrabold text-[#f7c85c] shadow-soft">
        م
      </span>
      <span className="leading-tight">
        <span className="block text-lg font-extrabold">ملورین</span>
        <span className="latin block text-[10px] font-semibold tracking-[.22em] text-muted">MELORIN</span>
      </span>
    </a>
  );
}

export function HeroVisual() {
  return (
    <div className="relative mx-auto w-full max-w-sm" aria-hidden="true">
      <div className="absolute -inset-6 rounded-full bg-accent/30 blur-3xl" />
      <div className="anim-float relative overflow-hidden rounded-4xl bg-hero p-6 shadow-lift">
        <div className="absolute -left-10 -top-14 h-44 w-44 rounded-full bg-[#f7c85c] opacity-70 blur-3xl" />
        <div className="relative flex items-center justify-between text-xs">
          <span className="rounded-full bg-white/10 px-3 py-1">سرویس شما</span>
          <span className="latin tracking-widest text-[#f7c85c]">MELORIN</span>
        </div>
        <div className="relative mt-10 grid place-items-center">
          <span className="absolute h-36 w-36 animate-ping rounded-full bg-[#86e0b8]/15" />
          <span className="absolute h-28 w-28 rounded-full border border-[#86e0b8]/30" />
          <span className="relative grid h-20 w-20 place-items-center rounded-full bg-[#86e0b8] text-[#0c1b33] shadow-[0_0_40px_#86e0b855]">
            <ShieldCheck size={36} strokeWidth={2} />
          </span>
        </div>
        <div className="relative mt-9 text-center">
          <div className="text-xl font-extrabold">متصل و امن</div>
          <div className="mt-1 text-xs text-white/55">یک لینک اشتراک، همه دستگاه‌ها</div>
        </div>
        <div className="relative mt-7 grid grid-cols-2 gap-3 text-xs">
          <div className="rounded-2xl bg-white/[.07] p-3">
            <div className="text-white/50">فعال‌سازی</div>
            <div className="mt-1 font-bold">پس از پرداخت</div>
          </div>
          <div className="rounded-2xl bg-white/[.07] p-3">
            <div className="text-white/50">پرداخت</div>
            <div className="mt-1 font-bold text-[#86e0b8]">کیف پول</div>
          </div>
        </div>
      </div>
      <div className="absolute -bottom-4 -right-3 flex items-center gap-2 rounded-2xl bg-[#f7c85c] px-4 py-3 text-sm font-extrabold text-[#10233f] shadow-lift">
        <Zap size={16} /> تحویل خودکار
      </div>
    </div>
  );
}

export const TG_RETRY = new Set(['user_denied', 'session_expired', 'unreachable', 'failed']);
export const TG_ERRORS = {
  user_denied: 'ورود در تلگرام رد شد.',
  session_expired: 'نشست ورود منقضی شد؛ دوباره امتحان کن.',
  registration_closed: 'ثبت‌نام جدید موقتاً بسته است.',
  account_disabled: 'حساب شما غیرفعال است. با پشتیبانی تماس بگیرید.',
  admin_use_panel: 'ورود ادمین فقط از پنل مدیریت انجام می‌شود.',
  unavailable: 'ورود با تلگرام در حال حاضر در دسترس نیست.',
  origin_mismatch: 'ورود با تلگرام در حال حاضر در دسترس نیست.',
  unreachable: 'اتصال به تلگرام برقرار نشد؛ کمی بعد دوباره امتحان کن.',
  failed: 'ورود با تلگرام انجام نشد؛ دوباره امتحان کن.',
};
