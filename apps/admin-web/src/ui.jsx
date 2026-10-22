import { useEffect, useState } from 'react';
import { Moon, Sun } from 'lucide-react';
import { getTheme, onTheme, toggleTheme } from './theme.js';

// Real enums from the Core API (order_state.py, ticket/payment/vpn/store models).
const S = {
  completed: ['b-ok', 'تکمیل‌شده'],
  paid: ['b-ok', 'پرداخت‌شده'],
  succeeded: ['b-ok', 'موفق'],
  active: ['b-ok', 'فعال'],
  healthy: ['b-ok', 'سالم'],
  applied: ['b-ok', 'اعمال‌شده'],
  answered: ['b-ok', 'پاسخ داده شد'],
  pending: ['b-wn', 'در انتظار'],
  payment_pending: ['b-wn', 'در انتظار پرداخت'],
  refund_pending: ['b-wn', 'در انتظار استرداد'],
  manual_review: ['b-wn', 'بررسی دستی'],
  review: ['b-wn', 'در بررسی'],
  receipt_submitted: ['b-wn', 'رسید ارسال شد'],
  awaiting_review: ['b-wn', 'در انتظار بررسی'],
  awaiting_details: ['b-in', 'منتظر دامنه و توکن'],
  open: ['b-wn', 'باز'],
  unknown: ['b-mu', 'نامشخص'],
  processing: ['b-in', 'در حال پردازش'],
  provisioning: ['b-in', 'در حال ساخت'],
  running: ['b-in', 'در حال اجرا'],
  failed: ['b-bd', 'ناموفق'],
  payment_failed: ['b-bd', 'پرداخت ناموفق'],
  provisioning_failed: ['b-bd', 'ساخت ناموفق'],
  unhealthy: ['b-bd', 'ناسالم'],
  expired: ['b-bd', 'منقضی'],
  refunded: ['b-mu', 'مسترد'],
  cancelled: ['b-mu', 'لغو شده'],
  disabled: ['b-mu', 'غیرفعال'],
  closed: ['b-mu', 'بسته'],
  archived: ['b-mu', 'آرشیو'],
  reversed: ['b-mu', 'برگشت‌خورده'],
  resolved: ['b-mu', 'حل‌شده'],
  ignored: ['b-mu', 'نادیده'],
};
export const Badge = ({ s }) => {
  const m = S[s];
  return <span className={`badge ${m ? m[0] : 'b-mu'}`}>{m ? m[1] : String(s ?? '-')}</span>;
};
export const isStatus = (v) => typeof v === 'string' && v in S;
export const dt = (v) => (v ? new Date(v).toLocaleString('fa-IR', { dateStyle: 'medium', timeStyle: 'short' }) : '-');
export const sid = (v) => String(v || '').slice(0, 8) || '-';

export function ThemeButton({ className = '' }) {
  const [t, setT] = useState(getTheme());
  useEffect(() => onTheme(setT), []);
  return (
    <button aria-label="تغییر پوسته" title="تغییر پوسته" onClick={toggleTheme} className={`btn btn-g ${className}`}>
      {t === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
    </button>
  );
}
export const tone = (s) => (S[s]?.[0] || 'b-mu').slice(2);
export const label = (s) => S[s]?.[1] || String(s);

// ---- Promise-based dialogs replacing window.confirm / window.prompt ----
let open_;
export const confirmDialog = (message, { title = 'تأیید عملیات', danger = false, ok = 'تأیید' } = {}) =>
  new Promise((res) => (open_ ? open_({ kind: 'c', title, message, danger, ok, res }) : res(false)));
// Single-button message (e.g. "why this cannot be deleted"); resolves when dismissed.
export const noticeDialog = (message, { title = 'توجه', ok = 'متوجه شدم' } = {}) =>
  new Promise((res) => (open_ ? open_({ kind: 'n', title, message, ok, res }) : res()));
export const promptDialog = (message, { title = 'ثبت توضیحات', ok = 'ثبت' } = {}) =>
  new Promise((res) => (open_ ? open_({ kind: 'p', title, message, ok, res }) : res(null)));
export function DialogHost() {
  const [d, setD] = useState(null);
  const [v, setV] = useState('');
  useEffect(() => {
    open_ = (x) => {
      setV('');
      setD(x);
    };
    return () => {
      open_ = null;
    };
  }, []);
  if (!d) return null;
  const done = (r) => {
    d.res(r);
    setD(null);
  };
  const cancel = () => done(d.kind === 'p' ? null : d.kind === 'n' ? undefined : false);
  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/55 p-4"
      onClick={cancel}
      onKeyDown={(e) => {
        if (e.key === 'Escape') cancel();
        if (e.key === 'Enter' && e.target.tagName === 'INPUT') done(v);
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={d.title}
        className="card rise w-full max-w-md p-6"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-lg font-extrabold">{d.title}</h3>
        <p className="mt-2 whitespace-pre-line text-sm leading-7 text-[var(--mu)]">{d.message}</p>
        {d.kind === 'p' && (
          <input
            autoFocus
            className="inp mt-4"
            value={v}
            onChange={(e) => setV(e.target.value)}
            placeholder="دلیل یا توضیح (اختیاری)"
          />
        )}
        <div className="mt-6 flex justify-start gap-2">
          <button
            autoFocus={d.kind !== 'p'}
            className={`btn ${d.danger ? '!bg-[var(--bd)] !text-white' : ''}`}
            onClick={() => done(d.kind === 'p' ? v : d.kind === 'n' ? undefined : true)}
          >
            {d.ok}
          </button>
          {d.kind !== 'n' && (
            <button className="btn btn-g" onClick={cancel}>
              انصراف
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
