import type { ReactNode } from 'react';
import { useState } from 'react';
import { authFetch } from './api.ts';
import { PasswordInput } from './ui.tsx';
import type { Json, Toast } from './types.ts';
import { box, inp, btn } from './adminExtraKit.tsx';

const Field = ({ label, children }: { label?: Json; children?: ReactNode }) => (
  <label className="block text-xs font-bold text-[var(--mu)]">
    {label}
    <div className="mt-1">{children}</div>
  </label>
);

export function ChangeAdminPassword({ api, toast }: { api?: Json; toast: Toast }) {
  const [v, setV] = useState({ current: '', next: '', confirm: '' });
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (v.next.length < 12) return toast('رمز جدید باید حداقل ۱۲ کاراکتر باشد');
    if (v.next !== v.confirm) return toast('تکرار رمز جدید یکسان نیست');
    setBusy(true);
    const r = await authFetch(api.base, '/api/v1/auth/admin/password', {
      method: 'POST',
      body: JSON.stringify({ current_password: v.current, new_password: v.next }),
    });
    const d = await r.json().catch(() => ({}));
    setBusy(false);
    if (!r.ok) return toast(d?.error?.message || d?.detail?.message || 'تغییر رمز ناموفق بود');
    setV({ current: '', next: '', confirm: '' });
    toast('رمز ادمین با موفقیت تغییر کرد');
  };
  return (
    <section className={`${box} space-y-4 p-5`}>
      <div>
        <h3 className="font-extrabold">امنیت حساب ادمین</h3>
        <p className="mt-1 text-xs text-[var(--mu)]">برای تغییر رمز، رمز فعلی لازم است. توکن نشست فعلی حفظ می‌شود.</p>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <Field label="رمز فعلی">
          <PasswordInput
            autoComplete="current-password"
            className={inp}
            value={v.current}
            onChange={(e: Json) => setV({ ...v, current: e.target.value })}
          />
        </Field>
        <Field label="رمز جدید">
          <PasswordInput
            autoComplete="new-password"
            className={inp}
            value={v.next}
            onChange={(e: Json) => setV({ ...v, next: e.target.value })}
          />
        </Field>
        <Field label="تکرار رمز جدید">
          <PasswordInput
            autoComplete="new-password"
            className={inp}
            value={v.confirm}
            onChange={(e: Json) => setV({ ...v, confirm: e.target.value })}
          />
        </Field>
      </div>
      <button disabled={busy || !v.current || !v.next || !v.confirm} className={btn} onClick={submit}>
        {busy ? 'در حال ذخیره...' : 'تغییر رمز'}
      </button>
    </section>
  );
}
