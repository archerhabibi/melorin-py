// GoogleLoginSettings.jsx — Admin > Settings > "ورود با گوگل"
// Collects the Google OAuth Client ID + switches and stores them on the server. A Client ID is public by design
// and the ID-token flow needs no client secret, so nothing secret is collected or stored here.

import { useEffect, useMemo, useState } from "react";
import { authFetch } from "./api.js";
import { Check, ChevronDown, Copy, ExternalLink, ShieldCheck } from "lucide-react";

const CLIENT_ID_RE = /^[0-9]{6,}-[A-Za-z0-9_-]+\.apps\.googleusercontent\.com$/;

const Field = ({ label, hint, error, children }) => (
  <label className="block text-xs font-bold text-[var(--mu)]">
    {label}
    <div className="mt-1">{children}</div>
    {error ? <span className="mt-1 block font-normal text-[var(--bd)]">{error}</span> : hint ? <span className="mt-1 block font-normal">{hint}</span> : null}
  </label>
);

const Switch = ({ on, set, label, hint }) => (
  <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-[var(--ln)] p-3">
    <input type="checkbox" className="mt-1" checked={on} onChange={(e) => set(e.target.checked)} />
    <span><span className="block text-sm font-bold">{label}</span>{hint && <span className="mt-0.5 block text-xs text-[var(--mu)]">{hint}</span>}</span>
  </label>
);

function CopyBox({ text }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); } catch { /* clipboard blocked: user can select the text */ }
  };
  return (
    <div className="flex items-center gap-2 rounded-lg border border-[var(--ln)] bg-[var(--bg)] px-3 py-2">
      <code dir="ltr" className="flex-1 select-all break-all text-xs">{text}</code>
      <button type="button" className="btn btn-g !px-2 !py-1" onClick={copy} aria-label="کپی">{done ? <Check size={14} /> : <Copy size={14} />}</button>
    </div>
  );
}

const Step = ({ n, title, children }) => (
  <li className="flex gap-3">
    <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-[var(--btn)] text-xs font-extrabold text-[var(--btntx)]">{n}</span>
    <div className="min-w-0 flex-1 space-y-1.5"><div className="font-bold">{title}</div><div className="space-y-1.5 text-xs leading-7 text-[var(--mu)]">{children}</div></div>
  </li>
);

function Guide({ origins }) {
  return (
    <details className="group rounded-xl border border-[var(--ln)]">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 p-4 text-sm font-bold">
        <span>راهنمای کامل اتصال به گوگل (گام‌به‌گام)</span>
        <ChevronDown size={16} className="transition group-open:rotate-180" />
      </summary>
      <div className="space-y-5 border-t border-[var(--ln)] p-4 text-sm">
        <p className="text-xs leading-7 text-[var(--mu)]">
          ملورین از روش <b>Google Identity Services (توکن ID)</b> استفاده می‌کند؛ پس فقط <b>Client ID</b> لازم است.
          <b> Client Secret، Redirect URI و دسترسی به API اضافه لازم نیست</b> و هیچ رمزی از گوگل در سرور ذخیره نمی‌شود.
        </p>
        <ol className="space-y-5">
          <Step n="۱" title="ساخت پروژه در Google Cloud">
            <p>وارد <a className="inline-flex items-center gap-1 text-[var(--ac)] underline" href="https://console.cloud.google.com/projectcreate" target="_blank" rel="noreferrer noopener">console.cloud.google.com <ExternalLink size={11} /></a> شوید (با حساب گوگلِ مالک کسب‌وکار، نه حساب شخصی موقت)، یک پروژه‌ی جدید بسازید و نام دلخواه (مثلاً Melorin) بدهید.</p>
          </Step>
          <Step n="۲" title="تنظیم صفحه‌ی رضایت (Google Auth Platform ← Branding / OAuth consent screen)">
            <p>نوع کاربر را <b>External</b> بگذارید. نام برنامه، ایمیل پشتیبانی و ایمیل تماس توسعه‌دهنده را وارد کنید. اگر دامنه‌ی فروشگاه دارید، آن را در <b>Authorized domains</b> اضافه کنید.</p>
            <p>دسترسی‌ها (Scopes) را <b>تغییر ندهید</b>: فقط <code dir="ltr">openid</code>، <code dir="ltr">email</code> و <code dir="ltr">profile</code> کافی است و نیاز به بازبینی گوگل ندارد.</p>
            <p className="rounded-lg bg-[var(--bg)] p-2"><b>مهم:</b> وضعیت انتشار (Publishing status) را از <b>Testing</b> به <b>In production</b> ببرید. در حالت Testing فقط «Test users» (حداکثر ۱۰۰ نفر) می‌توانند وارد شوند و مشتریان عادی خطای «access blocked» می‌گیرند.</p>
          </Step>
          <Step n="۳" title="ساخت OAuth Client ID">
            <p>از بخش <b>Clients</b> (یا APIs &amp; Services ← Credentials) گزینه‌ی <b>Create client / Create credentials ← OAuth client ID</b> را بزنید و <b>Application type = Web application</b> را انتخاب کنید.</p>
            <p>در <b>Authorized JavaScript origins</b> همه‌ی آدرس‌های زیر را اضافه کنید (هر کدام یک ردیف جدا). مبدأ فقط شامل <code dir="ltr">https://دامنه[:پورت]</code> است؛ بدون مسیر و بدون «/» پایانی. به‌جز <code dir="ltr">localhost</code>، آدرس باید HTTPS باشد:</p>
            <div className="space-y-1.5">{origins.map((o) => <CopyBox key={o} text={o} />)}</div>
            <p>بخش <b>Authorized redirect URIs</b> را <b>خالی</b> بگذارید.</p>
            <p>تغییرات گوگل ممکن است از چند دقیقه تا چند ساعت طول بکشد تا اعمال شود.</p>
          </Step>
          <Step n="۴" title="کپی Client ID">
            <p>بعد از ساخت، مقدار <b>Client ID</b> را کپی کنید. شکل آن این است: <code dir="ltr">123456789012-abc123def456.apps.googleusercontent.com</code></p>
          </Step>
          <Step n="۵" title="ثبت در ملورین">
            <p>Client ID را در فیلد بالا بچسبانید، سوئیچ «فعال‌سازی» را روشن و <b>ذخیره</b> کنید. سپس <b>تست اتصال</b> را بزنید تا مطمئن شوید سرور به گوگل دسترسی خروجی دارد. دکمه‌ی «ورود با گوگل» بدون نیاز به build مجدد در فروشگاه و پنل ظاهر می‌شود.</p>
          </Step>
          <Step n="۶" title="آزمایش ورود">
            <p><b>مشتریان:</b> در فروشگاه، از پنجره‌ی ورود روی «ورود با گوگل» بزنید. حساب جدید خودکار ساخته می‌شود؛ اگر ایمیل تأییدشده‌ی گوگل با ایمیلِ یک حساب موجود یکی باشد، به همان حساب وصل می‌شود.</p>
            <p><b>ادمین:</b> فقط وقتی کار می‌کند که ایمیل حساب گوگل <b>دقیقاً برابر ایمیل ادمین</b> باشد و TOTP فعال باشد. ابتدا کد TOTP را در صفحه‌ی ورود پنل وارد کنید، بعد روی «ورود با گوگل» بزنید. ورود ادمین با گوگل هرگز TOTP را دور نمی‌زند.</p>
          </Step>
        </ol>
        <div className="rounded-xl border border-[var(--ln)] p-3">
          <div className="mb-2 flex items-center gap-2 font-bold"><ShieldCheck size={16} />عیب‌یابی خطاهای رایج</div>
          <ul className="list-disc space-y-1.5 pr-5 text-xs leading-7 text-[var(--mu)]">
            <li><code dir="ltr">origin_mismatch</code> / <code dir="ltr">idpiframe_initialization_failed</code>: آدرس سایتی که در آن هستید دقیقاً در Authorized JavaScript origins نیست (http/https، www، پورت را بررسی کنید).</li>
            <li><code dir="ltr">Error 403: access_denied</code> یا «access blocked»: برنامه هنوز در حالت Testing است یا کاربر در Test users نیست.</li>
            <li><code dir="ltr">invalid_client</code> / «The OAuth client was not found»: Client ID اشتباه کپی شده یا حذف شده است.</li>
            <li>دکمه نمایش داده نمی‌شود: ورود گوگل غیرفعال است، Client ID خالی است، یا ورودِ همان بخش (ادمین/مشتری) در بالا خاموش است. مسدودکننده‌ی تبلیغ یا CSP هم می‌تواند اسکریپت <code dir="ltr">accounts.google.com/gsi/client</code> را ببندد.</li>
            <li>«توکن Google نامعتبر است» هنگام ورود: Client ID ذخیره‌شده با Client ID پروژه‌ای که توکن را صادر کرده یکی نیست، یا ساعت سرور درست نیست.</li>
            <li>تست اتصال ناموفق: سرور API باید بتواند به <code dir="ltr">oauth2.googleapis.com</code> روی پورت ۴۴۳ وصل شود (فایروال، DNS یا پروکسی خروجی را بررسی کنید).</li>
            <li>پنجره‌ی One Tap بعد از چند بار بستنِ کاربر برای مدتی نمایش داده نمی‌شود (cooldown خودِ گوگل)؛ چند دقیقه بعد یا در پنجره‌ی ناشناس دوباره امتحان کنید.</li>
          </ul>
        </div>
      </div>
    </details>
  );
}

export default function GoogleLoginSettings({ api, toast }) {
  const call = (p, o = {}) => authFetch(api.base, p, o);
  const [cfg, setCfg] = useState(null);
  const [busy, setBusy] = useState("");
  const [testResult, setTestResult] = useState(null);

  const load = () => call("/api/v1/admin/integrations")
    .then((r) => (r.ok ? r.json() : Promise.reject()))
    .then((d) => setCfg(d.google))
    .catch(() => toast("دریافت تنظیمات گوگل ناموفق بود"));
  useEffect(() => { load(); }, []);

  const origins = useMemo(() => {
    const here = window.location.origin;
    return [...new Set([here, ...(cfg?.suggested_origins || [])])];
  }, [cfg]);

  if (!cfg) return null;

  const id = (cfg.client_id || "").trim();
  const idError = id && !CLIENT_ID_RE.test(id) ? "فرمت Client ID درست نیست (باید به .apps.googleusercontent.com ختم شود)." : "";
  const set = (k) => (v) => { setCfg({ ...cfg, [k]: v }); setTestResult(null); };
  const canSave = !idError && (!cfg.enabled || (id && (cfg.admin_login || cfg.store_login)));

  const save = async () => {
    setBusy("save");
    const r = await call("/api/v1/admin/integrations/google", { method: "PUT", body: JSON.stringify({ enabled: cfg.enabled, client_id: id, admin_login: cfg.admin_login, store_login: cfg.store_login }) });
    const d = await r.json().catch(() => ({}));
    setBusy("");
    if (!r.ok) return toast(d?.error?.message || d?.detail?.message || "ذخیره ناموفق بود");
    toast("تنظیمات ورود با گوگل ذخیره شد");
    load();
  };
  const test = async () => {
    setBusy("test");
    const r = await call("/api/v1/admin/integrations/google/test", { method: "POST", body: "{}" });
    const d = await r.json().catch(() => ({}));
    setBusy("");
    setTestResult(r.ok ? d : { ok: false, error: d?.error?.message || "تست انجام نشد" });
  };

  const sourceLabel = cfg.source === "panel" ? "ذخیره‌شده در پنل" : cfg.source === "env" ? "از متغیر محیطی سرور (هنوز در پنل ذخیره نشده)" : "تنظیم نشده";
  return (
    <section className="card space-y-5 p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-extrabold">ورود با گوگل <span className="text-xs font-normal text-[var(--mu)]">(اختیاری)</span></h3>
        <span className={`badge ${cfg.enabled && id ? "b-ok" : "b-mu"}`}>{cfg.enabled && id ? "فعال" : "غیرفعال"}</span>
      </div>
      <p className="text-xs leading-7 text-[var(--mu)]">منبع تنظیم فعلی: {sourceLabel}. تغییرات بلافاصله و بدون build مجدد در فروشگاه و صفحه‌ی ورود پنل اعمال می‌شود.</p>

      <div className="grid gap-3 md:grid-cols-3">
        <Switch on={cfg.enabled} set={set("enabled")} label="فعال‌سازی ورود با گوگل" hint="کلید اصلی؛ با خاموش بودن، دکمه‌ی گوگل هیچ‌جا نمایش داده نمی‌شود." />
        <Switch on={cfg.store_login} set={set("store_login")} label="ورود مشتریان (فروشگاه)" hint="دکمه‌ی گوگل در پنجره‌ی ورود فروشگاه." />
        <Switch on={cfg.admin_login} set={set("admin_login")} label="ورود ادمین (همین پنل)" hint="همچنان نیازمند TOTP است." />
      </div>

      <Field label="Google OAuth Client ID" error={idError} hint="از Google Cloud Console ← Credentials. نوع Client باید Web application باشد. Client Secret لازم نیست.">
        <input dir="ltr" spellCheck={false} autoComplete="off" className="inp font-mono text-xs" value={cfg.client_id} onChange={(e) => set("client_id")(e.target.value)} placeholder="123456789012-abc123def456.apps.googleusercontent.com" />
      </Field>

      <div className="space-y-2">
        <div className="text-xs font-bold text-[var(--mu)]">Authorized JavaScript origins که باید در گوگل ثبت شوند</div>
        <div className="grid gap-1.5 md:grid-cols-2">{origins.map((o) => <CopyBox key={o} text={o} />)}</div>
        <p className="text-xs text-[var(--mu)]">اولین مورد، آدرسی است که همین پنل از آن باز شده است. اگر فروشگاه یا پنل دامنه‌ی دیگری هم دارند، همان‌ها را نیز اضافه کنید.</p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button disabled={busy === "save" || !canSave} className="btn" onClick={save}>{busy === "save" ? "در حال ذخیره..." : "ذخیره"}</button>
        <button disabled={busy === "test" || !id || !!idError} className="btn btn-g" onClick={test}>{busy === "test" ? "در حال تست..." : "تست اتصال سرور به گوگل"}</button>
        {testResult && <span className={`text-xs font-bold ${testResult.ok ? "text-[var(--ok)]" : "text-[var(--bd)]"}`}>{testResult.ok ? "اتصال سرور به گوگل برقرار است." : `ناموفق: ${testResult.error || ""}`}</span>}
      </div>
      <p className="text-xs text-[var(--mu)]">«تست اتصال» روی مقدار ذخیره‌شده کار می‌کند؛ ابتدا ذخیره کنید. این تست فقط دسترسی خروجی سرور و فرمت Client ID را بررسی می‌کند؛ درستیِ Origin‌ها فقط با یک ورود واقعی مشخص می‌شود.</p>

      <Guide origins={origins} />
    </section>
  );
}
