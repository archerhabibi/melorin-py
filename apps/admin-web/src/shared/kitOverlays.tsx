import { digits } from './kitFormat.ts';
import type { ReactNode } from 'react';
import { useState } from 'react';
import { Check, Copy, Eye, EyeOff, X } from 'lucide-react';
import { confirmDialog } from './ui.tsx';
import { backdropProps, useDialog } from './useDialog.ts';
import type { Json } from './types.ts';

/** Number input showing grouped digits; `value` is a string of ASCII digits. */
export function NumInput({
  value,
  onChange,
  placeholder,
  suffix,
  ...rest
}: {
  value?: Json;
  onChange?: Json;
  placeholder?: Json;
  suffix?: Json;
  [k: string]: Json;
}) {
  const shown = value === '' ? '' : Number(value).toLocaleString('en-US');
  return (
    <div className="relative">
      <input
        {...rest}
        dir="ltr"
        inputMode="numeric"
        className={`inp ${suffix ? '!pr-14' : ''}`}
        value={shown}
        placeholder={placeholder}
        onChange={(e) => onChange(digits(e.target.value).replace(/^0+(?=\d)/, ''))}
      />
      {suffix && (
        <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[11px] font-bold text-[var(--mu)]">
          {suffix}
        </span>
      )}
    </div>
  );
}

/** Right-side drawer with dirty-guard on close, sticky footer and server-error slot. */
export function Drawer({
  title,
  subtitle,
  icon,
  dirty,
  busy,
  onClose,
  children,
  footer,
  error,
  danger,
}: {
  title?: Json;
  subtitle?: Json;
  icon?: Json;
  dirty?: Json;
  busy?: Json;
  onClose?: Json;
  children?: ReactNode;
  footer?: Json;
  error?: Json;
  danger?: Json;
}) {
  const close = async () => {
    if (busy) return;
    if (
      dirty &&
      !(await confirmDialog('تغییرات ذخیره‌نشده از بین می‌رود. بسته شود؟', {
        title: 'بستن بدون ذخیره',
        danger: true,
        ok: 'بستن',
      }))
    )
      return;
    onClose();
  };
  const ref = useDialog(close);
  return (
    <div className="fixed inset-0 z-50">
      <div className="pv-fade absolute inset-0 bg-black/55" {...backdropProps(close)} />
      <aside
        ref={ref}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        dir="rtl"
        className="pv-drawer absolute inset-y-0 right-0 flex w-full max-w-2xl flex-col border-l border-[var(--ln)] bg-[var(--bg)] shadow-2xl"
      >
        <header className="flex items-center gap-3 border-b border-[var(--ln)] bg-[linear-gradient(180deg,var(--sf2),var(--sf))] px-5 py-4">
          {icon}
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-lg font-extrabold">{title}</h2>
            {subtitle && <p className="mt-0.5 truncate text-xs text-[var(--mu)]">{subtitle}</p>}
          </div>
          {dirty && <span className="badge b-wn">تغییرات ذخیره‌نشده</span>}
          <button className="btn btn-g !px-2" aria-label="بستن" onClick={close} disabled={busy}>
            <X size={16} />
          </button>
        </header>
        <div className="flex-1 space-y-4 overflow-y-auto bg-[var(--bg)] p-4 sm:p-5">{children}</div>
        <footer className="border-t border-[var(--ln)] bg-[var(--sf)] px-5 py-3">
          {error && (
            <p role="alert" className="mb-3 rounded-lg bg-[var(--bdb)] p-3 text-xs leading-6 text-[var(--bd)]">
              {error}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            {footer}
            <button className="btn btn-g !py-2 !text-sm" onClick={close} disabled={busy}>
              انصراف
            </button>
            {danger && <span className="mr-auto">{danger}</span>}
          </div>
        </footer>
      </aside>
    </div>
  );
}
export const Saved = ({ on }: { on?: Json }) =>
  on ? (
    <span className="inline-flex items-center gap-1 text-xs font-bold text-[var(--ok)]">
      <Check size={14} />
      ذخیره شد
    </span>
  ) : null;

// ---------- copy / secret inputs (shared by the panel forms) ----------
export function CopyButton({ text, label = 'کپی آدرس' }: { text?: Json; label?: Json }) {
  const [ok, setOk] = useState(false);
  return (
    <button
      type="button"
      className="btn btn-g !px-2"
      aria-label={label}
      title={label}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setOk(true);
          setTimeout(() => setOk(false), 1400);
        } catch {
          /* clipboard unavailable */
        }
      }}
    >
      {ok ? <Check size={14} /> : <Copy size={14} />}
    </button>
  );
}
export function Secret({ value, onChange, placeholder }: { value?: Json; onChange?: Json; placeholder?: Json }) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <input
        dir="ltr"
        autoComplete="off"
        spellCheck={false}
        type={show ? 'text' : 'password'}
        className="inp !pl-10"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
      <button
        type="button"
        aria-label={show ? 'پنهان‌کردن' : 'نمایش'}
        className="absolute left-2 top-1/2 -translate-y-1/2 text-[var(--mu)]"
        onClick={() => setShow(!show)}
      >
        {show ? <EyeOff size={16} /> : <Eye size={16} />}
      </button>
    </div>
  );
}
