import type { ChangeEvent, KeyboardEvent, ReactNode } from 'react';
import { useEffect, useState } from 'react';
import { CircleAlert, ShieldAlert } from 'lucide-react';
import { setTokens } from './auth.ts';
import { PasswordInput, ThemeButton } from './ui.tsx';
import { GoogleSignInButton, useGoogleConfig } from './GoogleSignIn.tsx';
import {
  codeFromResponse,
  failureFromError,
  LoginRequestError,
  sanitizeTotp,
  type LoginChannel,
  type LoginFailure,
} from './loginErrors.ts';

/** The token pair of a successful sign-in, as far as this form needs to look at it. */
interface TokenReply {
  access_token?: string;
  is_admin?: boolean;
  [key: string]: unknown;
}

// Renders its children (divider + button + hint) only when Google sign-in is enabled for the admin panel.
function GoogleGate({ children }: { children?: ReactNode }) {
  return useGoogleConfig() ? <>{children}</> : null;
}

function GoogleSignInButtonBlock({
  totpReady,
  busy,
  onCredential,
}: {
  totpReady?: boolean;
  busy?: boolean;
  onCredential: (idToken: string) => void | Promise<void>;
}) {
  return (
    <GoogleGate>
      <div className="my-5 flex items-center gap-3">
        <span className="h-px flex-1 bg-[var(--ln)]" />
        <span className="text-xs text-[var(--mu)]">یا</span>
        <span className="h-px flex-1 bg-[var(--ln)]" />
      </div>
      <GoogleSignInButton onCredential={onCredential} text="signin_with" disabled={busy || !totpReady} />
      <p className="mt-2 text-center text-xs leading-6 text-[var(--mu)]" aria-live="polite">
        {totpReady
          ? 'ورود ادمین با گوگل فقط برای حساب ادمین با TOTP فعال کار می‌کند.'
          : 'برای ورود با گوگل، ابتدا کد TOTP را در فیلد بالا وارد کنید.'}
      </p>
    </GoogleGate>
  );
}

/** One failure notice. Red = something to correct (e-mail/password), amber = a code or a wait. */
function FailureNotice({ failure, id }: { failure: LoginFailure; id: string }) {
  const danger = failure.tone === 'danger';
  const Icon = failure.area === 'totp' ? ShieldAlert : CircleAlert;
  return (
    <div
      id={id}
      role="alert"
      data-testid={`login-failure-${failure.area}`}
      data-code={failure.code}
      className={`mt-3 flex items-start gap-2.5 rounded-xl p-3 text-sm ${
        danger ? 'bg-[var(--bdb)] text-[var(--bd)]' : 'bg-[var(--wnb)] text-[var(--wn)]'
      }`}
    >
      <Icon size={18} className="mt-0.5 shrink-0" aria-hidden />
      <div>
        <div className="font-bold">{failure.title}</div>
        {failure.hint && <div className="mt-1 text-xs leading-6 opacity-90">{failure.hint}</div>}
      </div>
    </div>
  );
}

export default function AdminAuth({ base, onSuccess }: { base?: string; onSuccess?: () => void }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [totp, setTotp] = useState('');
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<LoginFailure | null>(null);

  const credentialsBad = failure?.area === 'credentials';
  const totpBad = failure?.area === 'totp';

  // Move the cursor to whatever the person has to fix, so the next keystroke goes to the right field.
  useEffect(() => {
    if (!failure) return;
    const target = failure.area === 'totp' ? 'tp' : failure.area === 'credentials' ? 'pw' : '';
    if (!target) return;
    const el = document.getElementById(target) as HTMLInputElement | null;
    el?.focus();
    el?.select();
  }, [failure]); // every failure is a new object, so the cursor moves again even for a repeated error

  function fail(error: unknown, channel: LoginChannel) {
    const f = failureFromError(error, channel);
    if (f.clearTotp) setTotp('');
    setFailure(f);
  }

  /** POST a sign-in request; resolves with the token pair or throws a LoginRequestError with the API's error code. */
  async function post(path: string, body: Record<string, unknown>, fallbackCode: string): Promise<TokenReply> {
    let r: Response;
    try {
      r = await fetch(`${base}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(body),
      });
    } catch {
      throw new LoginRequestError('NETWORK_ERROR');
    }
    const payload = await r.json().catch(() => ({}));
    if (!r.ok) throw new LoginRequestError(codeFromResponse(r.status, payload, fallbackCode), r.status);
    return payload;
  }

  // ───── password login ─────
  async function login() {
    setBusy(true);
    setFailure(null);
    try {
      const payload = await post(
        '/api/v1/auth/password/login',
        { email, password, totp_code: totp || undefined },
        'LOGIN_FAILED',
      );
      setTokens(payload);
      onSuccess?.();
    } catch (e: unknown) {
      fail(e, 'password');
    } finally {
      setBusy(false);
    }
  }

  // ───── Google login ─────
  async function handleGoogleCredential(idToken: string) {
    setBusy(true);
    setFailure(null);
    try {
      const payload = await post(
        '/api/v1/auth/google',
        { id_token: idToken, totp_code: totp || undefined },
        'GOOGLE_LOGIN_FAILED',
      );
      if (!payload.is_admin) throw new LoginRequestError('NOT_ADMIN', 200);
      setTokens(payload);
      onSuccess?.();
    } catch (e: unknown) {
      fail(e, 'google');
    } finally {
      setBusy(false);
    }
  }

  const onKey = (e: KeyboardEvent<HTMLElement>) => {
    if (e.key === 'Enter' && email && password && !busy) login();
  };

  return (
    <main dir="rtl" className="relative grid min-h-screen place-items-center overflow-hidden bg-[var(--nav)] p-6">
      <div
        aria-hidden
        className="pointer-events-none absolute -left-24 -top-24 h-96 w-96 rounded-full bg-[#f4c95d]/10 blur-3xl"
      />
      <div className="absolute left-5 top-5">
        <ThemeButton />
      </div>

      <section role="presentation" className="card rise w-full max-w-md p-8 shadow-2xl" onKeyDown={onKey}>
        {/* Brand */}
        <div className="mb-8 flex items-center gap-3">
          <div className="grid h-12 w-12 place-items-center rounded-2xl bg-[#f4c95d] text-xl font-extrabold text-[#0f1f38]">
            م
          </div>
          <div>
            <div className="font-extrabold">ملورین</div>
            <div className="text-xs tracking-[.16em] text-[var(--mu)]">CONTROL ROOM</div>
          </div>
        </div>

        <div className="text-sm font-bold text-[var(--ac)]">ورود امن مدیر</div>
        <h1 className="mt-2 text-3xl font-extrabold">اتاق کنترل آماده‌ست.</h1>

        {/* Password form */}
        <label htmlFor="em" className="mt-6 block text-sm font-bold">
          ایمیل مدیر
        </label>
        <input
          id="em"
          dir="ltr"
          type="email"
          autoComplete="username"
          value={email}
          onChange={(e) => {
            setEmail(e.target.value);
            if (credentialsBad) setFailure(null);
          }}
          aria-invalid={credentialsBad || undefined}
          className="inp mt-2"
          placeholder="admin@example.com"
        />

        <label htmlFor="pw" className="mt-4 block text-sm font-bold">
          رمز عبور
        </label>
        <PasswordInput
          id="pw"
          autoComplete="current-password"
          value={password}
          onChange={(e: ChangeEvent<HTMLInputElement>) => {
            setPassword(e.target.value);
            if (credentialsBad) setFailure(null);
          }}
          aria-invalid={credentialsBad || undefined}
          aria-describedby={credentialsBad ? 'login-failure-credentials' : undefined}
          className="inp"
          wrapClassName="mt-2"
        />
        {credentialsBad && failure && <FailureNotice failure={failure} id="login-failure-credentials" />}

        <label htmlFor="tp" className="mt-4 block text-sm font-bold">
          کد TOTP
        </label>
        <input
          id="tp"
          dir="ltr"
          inputMode="numeric"
          autoComplete="one-time-code"
          value={totp}
          onChange={(e) => {
            setTotp(sanitizeTotp(e.target.value));
            if (totpBad) setFailure(null);
          }}
          aria-invalid={totpBad || undefined}
          aria-describedby={totpBad ? 'login-failure-totp' : undefined}
          data-tone={totpBad ? 'warning' : undefined}
          className="inp mt-2 text-center tracking-[.5em]"
          placeholder="------"
        />
        {totpBad && failure && <FailureNotice failure={failure} id="login-failure-totp" />}

        {failure?.area === 'form' && <FailureNotice failure={failure} id="login-failure-form" />}

        <button disabled={busy || !email || !password} onClick={login} className="btn mt-5 w-full py-3">
          {busy ? 'در حال بررسی...' : 'ورود به داشبورد'}
        </button>

        {/* Sign in with Google (official button). Admin sign-in still needs the TOTP code, so it unlocks once the code is typed. */}
        <GoogleSignInButtonBlock totpReady={totp.length >= 6} busy={busy} onCredential={handleGoogleCredential} />
      </section>
    </main>
  );
}
