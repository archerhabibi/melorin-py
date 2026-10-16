import { useEffect, useRef, useState } from "react";
import { X, CheckCircle2, AlertCircle, Info, Moon, Sun, Inbox } from "lucide-react";

export const fa = (n) => new Intl.NumberFormat("fa-IR").format(Number(n) || 0);
// Date + time, e.g. ۱۴۰۵/۰۷/۲۱، ۱۴:۳۰
const FD = { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false };
export const fd = (d) => (d ? new Date(d).toLocaleString("fa-IR", FD) : "—");

/* ---------- theme ---------- */
const KEY = "melorin-theme";
const read = () => { try { return localStorage.getItem(KEY); } catch { return null; } };
export function initTheme() {
  const t = read() || (window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  document.documentElement.dataset.theme = t;
}
export function ThemeToggle() {
  const [t, setT] = useState(() => document.documentElement.dataset.theme || "light");
  const flip = () => {
    const n = t === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = n; setT(n);
    try { localStorage.setItem(KEY, n); } catch { /* storage may be unavailable */ }
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", n === "dark" ? "#08111f" : "#10233f");
  };
  return <button onClick={flip} aria-label={t === "dark" ? "تم روشن" : "تم تیره"} className="grid h-10 w-10 place-items-center rounded-full ring-1 ring-line transition hover:bg-surface2">{t === "dark" ? <Sun size={18} /> : <Moon size={18} />}</button>;
}

/* ---------- status badges (Persian labels, raw fallback) ---------- */
const TONES = {
  good: "bg-mint-soft text-mint", warn: "bg-accent-soft text-ink", bad: "bg-danger-soft text-danger", neutral: "bg-surface2 text-muted",
};
const STATUS = {
  completed: ["تکمیل‌شده", "good"], succeeded: ["موفق", "good"], active: ["فعال", "good"], paid: ["پرداخت‌شده", "good"], approved: ["تأییدشده", "good"], answered: ["پاسخ داده شد", "good"],
  pending: ["در انتظار", "warn"], processing: ["در حال پردازش", "warn"], provisioning: ["در حال تحویل", "warn"], open: ["باز", "warn"], pending_review: ["در انتظار بررسی", "warn"], created: ["ایجاد شد", "warn"], near_expiry: ["نزدیک انقضا", "warn"], disabled: ["غیرفعال", "neutral"], closed: ["بسته", "neutral"],
  failed: ["ناموفق", "bad"], provisioning_failed: ["خطا در تحویل", "bad"], expired: ["منقضی", "bad"], cancelled: ["لغو شد", "neutral"], awaiting_details: ["منتظر دامنه و توکن", "warn"], refunded: ["بازپرداخت شد", "neutral"], rejected: ["ردشده", "bad"], revoked: ["ابطال‌شده", "bad"], suspended: ["تعلیق", "bad"],
};
export function StatusBadge({ status }) {
  const [label, tone] = STATUS[String(status || "").toLowerCase()] || [status || "—", "neutral"];
  return <span className={`badge ${TONES[tone]}`}><span className="h-1.5 w-1.5 rounded-full bg-current" />{label}</span>;
}

/* ---------- small building blocks ---------- */
export function Empty({ text, icon: Icon = Inbox, children }) {
  return <div className="rounded-2xl border border-dashed border-line px-6 py-12 text-center"><Icon className="mx-auto text-muted" size={28} strokeWidth={1.6} /><p className="mt-3 text-sm text-muted">{text}</p>{children}</div>;
}
export function Loading({ rows = 3 }) {
  return <div className="space-y-3" role="status" aria-label="در حال دریافت">{Array.from({ length: rows }).map((_, i) => <div key={i} className="skeleton h-20" />)}</div>;
}
export function PageTitle({ eyebrow, title, children }) {
  return <div className="mb-8 flex flex-wrap items-end justify-between gap-4"><div><div className="eyebrow">{eyebrow}</div><h2 className="mt-1 text-3xl font-extrabold tracking-tight md:text-4xl">{title}</h2></div><div className="flex flex-wrap gap-2">{children}</div></div>;
}

export function Modal({ onClose, title, children, label }) {
  const ref = useRef(null);
  useEffect(() => {
    const prev = document.activeElement;
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    ref.current?.querySelector("input,button")?.focus();
    return () => { document.removeEventListener("keydown", onKey); document.body.style.overflow = ""; prev?.focus?.(); };
  }, []);
  return <div className="fixed inset-0 z-50 grid place-items-end bg-navy/60 p-0 backdrop-blur-sm sm:place-items-center sm:p-4" onClick={onClose}>
    <div ref={ref} role="dialog" aria-modal="true" aria-label={label || title} onClick={(e) => e.stopPropagation()} className="anim-pop relative w-full max-w-md rounded-t-4xl bg-surface p-7 shadow-lift sm:rounded-4xl">
      <button onClick={onClose} aria-label="بستن" className="absolute left-4 top-4 grid h-9 w-9 place-items-center rounded-full text-muted transition hover:bg-surface2"><X size={18} /></button>
      {title && <h3 className="text-2xl font-extrabold">{title}</h3>}
      {children}
    </div>
  </div>;
}

export function Toast({ message }) {
  if (!message) return null;
  const bad = /ناموفق|نامعتبر|نشد|نادرست|خطا|در دسترس نیست/.test(message);
  const Icon = bad ? AlertCircle : /ثبت|ارسال|ذخیره|کپی|خوش|فعال|شد/.test(message) ? CheckCircle2 : Info;
  return <div role="status" aria-live="polite" className="anim-pop fixed inset-x-4 bottom-24 z-[60] mx-auto flex w-fit max-w-[92vw] items-center gap-2.5 rounded-full bg-hero px-5 py-3 text-sm font-semibold shadow-lift md:bottom-8"><Icon size={18} className={bad ? "text-[#f79680]" : "text-[#86e0b8]"} />{message}</div>;
}
