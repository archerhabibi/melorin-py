import { useState } from "react";
import { setTokens } from "./auth.js";

export default function AdminAuth({ base, onSuccess }) {
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [step, setStep] = useState("email");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function requestCode() {
    setBusy(true); setError("");
    try {
      const r = await fetch(`${base}/api/v1/auth/email/request-code`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email }),
      });
      if (!r.ok) throw new Error();
      setStep("code");
    } catch { setError("ارسال کد ناموفق بود. ایمیل و اتصال API را بررسی کنید."); }
    finally { setBusy(false); }
  }

  async function verifyCode() {
    setBusy(true); setError("");
    try {
      const r = await fetch(`${base}/api/v1/auth/email/verify-code`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email, code }),
      });
      if (!r.ok) throw new Error();
      const pair = await r.json();
        setTokens(pair);
      onSuccess();
    } catch { setError("کد نامعتبر یا منقضی شده است."); }
    finally { setBusy(false); }
  }

  return <main dir="rtl" className="grid min-h-screen place-items-center bg-[#11243f] p-6 text-[#11243f]">
    <section className="w-full max-w-md rounded-[2rem] bg-[#f8f9f6] p-8 shadow-2xl">
      <div className="mb-8 flex items-center gap-3">
        <div className="grid h-12 w-12 place-items-center rounded-2xl bg-[#f4c95d] text-xl font-extrabold">م</div>
        <div><div className="font-extrabold">ملورین</div><div className="text-xs tracking-[.16em] text-[#71808b]">CONTROL ROOM</div></div>
      </div>
      <div className="text-sm font-bold text-[#b55328]">ورود امن مدیر</div>
      <h1 className="mt-2 text-3xl font-extrabold">اتاق کنترل آماده‌ست.</h1>
      <p className="mt-3 text-sm leading-7 text-[#71808b]">برای ورود، کد یک‌بارمصرف به ایمیل ادمین ارسال می‌شود.</p>
      <label className="mt-7 block text-sm font-bold">ایمیل مدیر</label>
      <input dir="ltr" type="email" value={email} onChange={e => setEmail(e.target.value)} disabled={step === "code"} className="mt-2 w-full rounded-xl border border-[#dce0dc] bg-white p-3 outline-none focus:border-[#b55328]" placeholder="admin@example.com" />
      {step === "code" && <><label className="mt-4 block text-sm font-bold">کد ورود</label><input dir="ltr" inputMode="numeric" value={code} onChange={e => setCode(e.target.value)} className="mt-2 w-full rounded-xl border border-[#dce0dc] bg-white p-3 text-center tracking-[.5em] outline-none focus:border-[#b55328]" placeholder="------" /></>}
      {error && <div className="mt-4 rounded-xl bg-[#fff2ee] p-3 text-sm font-bold text-[#91390c]">{error}</div>}
      <button disabled={busy || !email || (step === "code" && !code)} onClick={step === "email" ? requestCode : verifyCode} className="mt-5 w-full rounded-xl bg-[#11243f] p-3.5 font-bold text-white disabled:opacity-40">{busy ? "در حال بررسی..." : step === "email" ? "ارسال کد ورود" : "ورود به داشبورد"}</button>
      {step === "code" && <button onClick={() => { setStep("email"); setCode(""); setError(""); }} className="mt-3 w-full p-2 text-sm font-bold text-[#71808b]">تغییر ایمیل</button>}
    </section>
  </main>;
}
