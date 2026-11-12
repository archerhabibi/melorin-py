// Public page opened from an admin invitation e-mail: #/accept-invite?t=<one-time token>.
// Three quiet steps: check the invite -> scan the authenticator QR code -> choose a password and prove the code.
// The token lives in the URL fragment (never sent to a server or a log) and in memory only.
import type { ChangeEvent } from 'react';
import { useMemo, useState } from 'react';
import { CheckCircle2, MailWarning, ShieldCheck, Smartphone } from 'lucide-react';
import { PasswordInput, ThemeButton } from './ui.tsx';
import type { AdminEnrollment, AdminInviteInfo } from './types.ts';

export const INVITE_HASH = '#/accept-invite';
export const isInviteHash = (hash: string) => hash === INVITE_HASH || hash.startsWith(`${INVITE_HASH}?`);
export const inviteToken = (hash: string) => new URLSearchParams(hash.split('?')[1] || '').get('t') || '';

/** Mirror of apps/api/melorin/domain/password_policy.py for live feedback; the server stays the judge. */
export const passwordChecks = (password: string, email = '') => {
  const local = email.split('@')[0].toLowerCase();
  const classes = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/].filter((re) => re.test(password)).length;
  return [
    { ok: password.length >= 12, text: 'حداقل ۱۲ نویسه' },
    { ok: classes >= 3, text: 'ترکیب سه نوع از: حرف کوچک، حرف بزرگ، عدد، نماد' },
    { ok: !(local.length >= 4 && password.toLowerCase().includes(local)), text: 'بدون بخشی از ایمیل شما' },
  ];
};

const post = async (base: string, path: string, body: Record<string, string>) => {
  const r = await fetch(`${base}/api/v1/auth/admin-invite/${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const payload = await r.json().catch(() => ({}));
  return {
    ok: r.ok,
    payload,
    message: payload?.error?.message as string | undefined,
    code: payload?.error?.code as string | undefined,
  };
};

const Shell = ({ children }: { children: React.ReactNode }) => (
  <main dir="rtl" className="relative grid min-h-screen place-items-center overflow-hidden bg-[var(--nav)] p-6">
    <div
      aria-hidden
      className="pointer-events-none absolute -left-24 -top-24 h-96 w-96 rounded-full bg-[#f4c95d]/10 blur-3xl"
    />
    <div className="absolute left-5 top-5">
      <ThemeButton />
    </div>
    <section className="card rise w-full max-w-md p-8 shadow-2xl">
      <div className="mb-7 flex items-center gap-3">
        <div className="grid h-12 w-12 place-items-center rounded-2xl bg-[#f4c95d] text-xl font-extrabold text-[#0f1f38]">
          م
        </div>
        <div>
          <div className="font-extrabold">ملورین</div>
          <div className="text-xs tracking-[.16em] text-[var(--mu)]">CONTROL ROOM</div>
        </div>
      </div>
      {children}
    </section>
  </main>
);

const toLogin = () => {
  window.location.hash = '';
  window.location.reload();
};

export default function AcceptInvite({ base }: { base: string }) {
  const token = useMemo(() => inviteToken(window.location.hash), []);
  const [step, setStep] = useState<'intro' | 'setup' | 'done' | 'invalid'>(token ? 'intro' : 'invalid');
  const [info, setInfo] = useState<AdminInviteInfo | null>(null);
  const [checked, setChecked] = useState(false);
  const [enroll, setEnroll] = useState<AdminEnrollment | null>(null);
  const [password, setPassword] = useState('');
  const [again, setAgain] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  // Look the invite up once, the first time the page needs it.
  if (token && !checked) {
    setChecked(true);
    post(base, 'inspect', { token }).then((r) => (r.ok ? setInfo(r.payload) : setStep('invalid')));
  }

  const begin = async () => {
    setBusy(true);
    setError('');
    const r = await post(base, 'enroll', { token });
    setBusy(false);
    if (!r.ok) return r.code === 'INVITE_INVALID' ? setStep('invalid') : setError(r.message || 'راه‌اندازی ناموفق بود');
    setEnroll(r.payload);
    setStep('setup');
  };

  const checks = passwordChecks(password, info?.email);
  const strong = checks.every((c) => c.ok);
  const ready = strong && password === again && /^\d{6,8}$/.test(code.trim());

  const finish = async () => {
    setBusy(true);
    setError('');
    const r = await post(base, 'accept', { token, password, totp_code: code.trim() });
    setBusy(false);
    if (r.ok) return setStep('done');
    if (r.code === 'INVITE_INVALID' || r.code === 'INVITE_LOCKED') return setStep('invalid');
    if (r.code === 'TOTP_INVALID') setCode('');
    setError(r.message || 'تکمیل راه‌اندازی ناموفق بود');
  };

  if (step === 'invalid')
    return (
      <Shell>
        <div className="grid h-12 w-12 place-items-center rounded-2xl bg-[var(--bdb)] text-[var(--bd)]">
          <MailWarning size={24} />
        </div>
        <h1 className="mt-4 text-2xl font-extrabold">لینک دعوت معتبر نیست</h1>
        <p className="mt-3 text-sm leading-7 text-[var(--mu)]">
          این لینک منقضی شده، قبلاً استفاده شده یا باطل شده است. از مالک پنل بخواهید دعوت تازه‌ای بفرستد.
        </p>
        <button className="btn btn-g mt-6 w-full py-3" onClick={toLogin}>
          رفتن به صفحه‌ی ورود
        </button>
      </Shell>
    );

  if (step === 'done')
    return (
      <Shell>
        <div className="grid h-12 w-12 place-items-center rounded-2xl bg-[var(--okb)] text-[var(--ok)]">
          <CheckCircle2 size={26} />
        </div>
        <h1 className="mt-4 text-2xl font-extrabold">حساب شما آماده است</h1>
        <p className="mt-3 text-sm leading-7 text-[var(--mu)]">
          حالا با ایمیل، رمز عبور و کد برنامه‌ی احراز هویت وارد شوید. توجه: هر کد فقط یک بار پذیرفته می‌شود؛ برای ورود
          اولین کد بعدی برنامه را صبر کنید.
        </p>
        <button className="btn mt-6 w-full py-3" onClick={toLogin}>
          ورود به پنل
        </button>
      </Shell>
    );

  if (step === 'intro')
    return (
      <Shell>
        <div className="text-sm font-bold text-[var(--ac)]">دعوت به پنل مدیریت</div>
        <h1 className="mt-2 text-2xl font-extrabold">
          {info ? `سلام ${info.display_name || ''}`.trim() : 'در حال بررسی دعوت…'}
        </h1>
        {info ? (
          <>
            <dl className="mt-5 divide-y divide-[var(--ln)] overflow-hidden rounded-xl border border-[var(--ln)] bg-[var(--sf)] text-sm">
              <div className="flex justify-between gap-3 px-4 py-2.5">
                <dt className="text-xs text-[var(--mu)]">ایمیل</dt>
                <dd dir="ltr" className="font-bold">
                  {info.email}
                </dd>
              </div>
              <div className="flex justify-between gap-3 px-4 py-2.5">
                <dt className="text-xs text-[var(--mu)]">نقش شما</dt>
                <dd className="font-bold">{info.role_label}</dd>
              </div>
              <div className="flex justify-between gap-3 px-4 py-2.5">
                <dt className="text-xs text-[var(--mu)]">اعتبار لینک تا</dt>
                <dd className="font-bold">{new Date(info.expires_at).toLocaleString('fa-IR')}</dd>
              </div>
            </dl>
            <p className="mt-4 text-sm leading-7 text-[var(--mu)]">
              برای امنیت، ورود به این پنل با رمز عبور و یک برنامه‌ی احراز هویت (Google Authenticator، Aegis، 1Password
              و…) انجام می‌شود. در گام بعد هر دو را برای خودتان می‌سازید؛ هیچ‌کس دیگری آن‌ها را نمی‌بیند.
            </p>
            {error && (
              <div role="alert" className="mt-4 rounded-xl bg-[var(--bdb)] p-3 text-sm font-bold text-[var(--bd)]">
                {error}
              </div>
            )}
            <button className="btn mt-5 w-full py-3" disabled={busy} onClick={begin}>
              {busy ? 'کمی صبر کنید…' : 'شروع راه‌اندازی'}
            </button>
          </>
        ) : (
          <div className="skel mt-5 h-24 w-full" />
        )}
      </Shell>
    );

  return (
    <Shell>
      <div className="text-sm font-bold text-[var(--ac)]">راه‌اندازی حساب</div>
      <h1 className="mt-2 text-2xl font-extrabold">برنامه‌ی احراز هویت و رمز عبور</h1>

      <div className="mt-5 flex items-start gap-3 rounded-xl border border-[var(--ln)] bg-[var(--sf)] p-4">
        <Smartphone size={20} className="mt-1 shrink-0 text-[var(--ac)]" />
        <div className="min-w-0 text-sm leading-7">
          <b>۱.</b> این کد QR را با برنامه‌ی احراز هویت اسکن کنید.
          {enroll && (
            <div className="mt-3 grid place-items-center">
              <img
                src={enroll.qr_data_uri}
                alt="کد QR برای افزودن حساب به برنامه‌ی احراز هویت"
                width={176}
                height={176}
                className="rounded-lg bg-white p-2"
              />
            </div>
          )}
          <details className="mt-2 text-xs text-[var(--mu)]">
            <summary className="cursor-pointer font-bold">اسکن نمی‌شود؟ کلید را دستی وارد کنید</summary>
            <code
              dir="ltr"
              className="mt-2 block break-all rounded-md bg-[var(--mb)] p-2 text-[13px] tracking-wider text-[var(--tx)]"
            >
              {enroll?.secret}
            </code>
          </details>
        </div>
      </div>

      <label htmlFor="ai-pw" className="mt-5 block text-sm font-bold">
        ۲. رمز عبور تازه
      </label>
      <PasswordInput
        id="ai-pw"
        autoComplete="new-password"
        value={password}
        onChange={(e: ChangeEvent<HTMLInputElement>) => setPassword(e.target.value)}
        className="inp"
        wrapClassName="mt-2"
      />
      <ul className="mt-2 space-y-1 text-xs" aria-label="شرایط رمز عبور">
        {checks.map((c) => (
          <li key={c.text} className={c.ok ? 'text-[var(--ok)]' : 'text-[var(--mu)]'}>
            {c.ok ? '✓' : '○'} {c.text}
          </li>
        ))}
      </ul>

      <label htmlFor="ai-pw2" className="mt-4 block text-sm font-bold">
        تکرار رمز عبور
      </label>
      <PasswordInput
        id="ai-pw2"
        autoComplete="new-password"
        value={again}
        onChange={(e: ChangeEvent<HTMLInputElement>) => setAgain(e.target.value)}
        className="inp"
        wrapClassName="mt-2"
      />
      {again && password !== again && <p className="mt-1 text-xs text-[var(--bd)]">تکرار رمز یکسان نیست.</p>}

      <label htmlFor="ai-code" className="mt-4 block text-sm font-bold">
        ۳. کد ۶ رقمی برنامه
      </label>
      <input
        id="ai-code"
        dir="ltr"
        inputMode="numeric"
        autoComplete="one-time-code"
        maxLength={8}
        value={code}
        onChange={(e) => setCode(e.target.value)}
        className="inp mt-2 text-center tracking-[.5em]"
        placeholder="------"
        onKeyDown={(e) => e.key === 'Enter' && ready && !busy && finish()}
      />

      {error && (
        <div role="alert" className="mt-4 rounded-xl bg-[var(--bdb)] p-3 text-sm font-bold text-[var(--bd)]">
          {error}
        </div>
      )}
      <button className="btn mt-5 w-full py-3" disabled={busy || !ready} onClick={finish}>
        <ShieldCheck size={16} />
        {busy ? 'در حال تکمیل…' : 'فعال‌سازی حساب'}
      </button>
    </Shell>
  );
}
