import { useEffect, useState } from "react";
import { setTokens } from "./auth.js";
import { ThemeButton } from "./ui.jsx";
import { GoogleSignInButton, useGoogleSignIn } from "./GoogleSignIn.jsx";

export default function AdminAuth({ base, onSuccess }) {
  const [email, setEmail]       = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp]         = useState("");
  const [busy, setBusy]         = useState(false);
  const [error, setError]       = useState("");

  // ───── password login ─────
  async function login() {
    setBusy(true); setError("");
    try {
      const r = await fetch(`${base}/api/v1/auth/password/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email, password, totp_code: totp || undefined }),
      });
      const payload = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(payload.code || "LOGIN_FAILED");
      setTokens(payload);
      onSuccess();
    } catch (e) {
      setError(
        e.message === "ADMIN_2FA_REQUIRED"
          ? "برای ادمین ابتدا TOTP را با مسیر bootstrap امن فعال کنید."
          : e.message === "TOTP_REQUIRED"
            ? "کد TOTP لازم است."
            : "ایمیل یا رمز عبور نادرست است."
      );
    } finally { setBusy(false); }
  }

  // ───── Google login ─────
  async function handleGoogleCredential(idToken) {
    setBusy(true); setError("");
    try {
      const r = await fetch(`${base}/api/v1/auth/google`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ id_token: idToken, totp_code: totp || undefined }),
      });
      const payload = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(payload.code || "GOOGLE_LOGIN_FAILED");
      if (!payload.is_admin) {
        throw new Error("NOT_ADMIN");
      }
      setTokens(payload);
      onSuccess();
    } catch (e) {
      setError(
        e.message === "NOT_ADMIN"
          ? "این حساب Google دسترسی ادمین ندارد."
          : e.message === "TOTP_REQUIRED"
            ? "ابتدا کد TOTP را در فیلد پایین وارد کنید، سپس دوباره روی ورود با گوگل بزنید."
            : e.message === "ADMIN_2FA_REQUIRED"
              ? "برای ادمین ابتدا TOTP را با مسیر bootstrap امن فعال کنید."
              : "ورود با Google ناموفق بود. دوباره تلاش کنید."
      );
    } finally { setBusy(false); }
  }

  useGoogleSignIn(handleGoogleCredential);

  const onKey = (e) => { if (e.key === "Enter" && email && password && !busy) login(); };

  return (
    <main dir="rtl" className="relative grid min-h-screen place-items-center overflow-hidden bg-[var(--nav)] p-6">
      <div aria-hidden className="pointer-events-none absolute -left-24 -top-24 h-96 w-96 rounded-full bg-[#f4c95d]/10 blur-3xl" />
      <div className="absolute left-5 top-5"><ThemeButton /></div>

      <section className="card rise w-full max-w-md p-8 shadow-2xl" onKeyDown={onKey}>
        {/* Brand */}
        <div className="mb-8 flex items-center gap-3">
          <div className="grid h-12 w-12 place-items-center rounded-2xl bg-[#f4c95d] text-xl font-extrabold text-[#0f1f38]">م</div>
          <div>
            <div className="font-extrabold">ملورین</div>
            <div className="text-xs tracking-[.16em] text-[var(--mu)]">CONTROL ROOM</div>
          </div>
        </div>

        <div className="text-sm font-bold text-[var(--ac)]">ورود امن مدیر</div>
        <h1 className="mt-2 text-3xl font-extrabold">اتاق کنترل آماده‌ست.</h1>

        {/* Google Sign-In */}
        <div className="mt-6">
          <GoogleSignInButton
            onCredential={handleGoogleCredential}
            label="ورود با گوگل (ادمین)"
            className="py-3"
          />
          <p className="mt-2 text-xs text-[var(--mu)]">ورود ادمین با گوگل هم به کد TOTP نیاز دارد؛ ابتدا کد را در فیلد زیر وارد کنید.</p>
        </div>

        {/* Divider */}
        <div className="my-5 flex items-center gap-3">
          <span className="h-px flex-1 bg-[var(--ln)]" />
          <span className="text-xs text-[var(--mu)]">یا با رمز عبور</span>
          <span className="h-px flex-1 bg-[var(--ln)]" />
        </div>

        {/* Password form */}
        <label htmlFor="em" className="block text-sm font-bold">ایمیل مدیر</label>
        <input id="em" dir="ltr" type="email" autoComplete="username"
          value={email} onChange={(e) => setEmail(e.target.value)}
          className="inp mt-2" placeholder="admin@example.com" />

        <label htmlFor="pw" className="mt-4 block text-sm font-bold">رمز عبور</label>
        <input id="pw" dir="ltr" type="password" autoComplete="current-password"
          value={password} onChange={(e) => setPassword(e.target.value)}
          className="inp mt-2" />

        <label htmlFor="tp" className="mt-4 block text-sm font-bold">کد TOTP</label>
        <input id="tp" dir="ltr" inputMode="numeric" autoComplete="one-time-code"
          maxLength={8} value={totp} onChange={(e) => setTotp(e.target.value)}
          className="inp mt-2 text-center tracking-[.5em]" placeholder="------" />

        {error && (
          <div role="alert" className="mt-4 rounded-xl bg-[var(--bdb)] p-3 text-sm font-bold text-[var(--bd)]">{error}</div>
        )}

        <button disabled={busy || !email || !password} onClick={login}
          className="btn mt-5 w-full py-3">
          {busy ? "در حال بررسی..." : "ورود به داشبورد"}
        </button>
      </section>
    </main>
  );
}
