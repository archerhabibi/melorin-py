// TelegramLoginSettings.jsx — Admin > Settings > "ورود با تلگرام"
// Two independent customer login methods share one master switch:
//   1) تأیید در ربات  — device-authorization flow inside the store's bot (needs no extra data);
//   2) ورود مستقیم    — Telegram Login (OpenID Connect): needs the bot's Client ID + Client Secret from @BotFather.
// The Client Secret is write-only: it is stored encrypted on the server and never sent back to the browser.

import { useEffect, useState } from "react";
import { authFetch } from "./api.js";
import { Check, ChevronDown, Copy, ExternalLink, Send, ShieldCheck } from "lucide-react";
import { CopyBox, Field, Step, Switch } from "./GoogleLoginSettings.jsx";

const CLIENT_ID_RE = /^[0-9]{5,20}$/;
const FIELDS = ["enabled", "store_login", "bot_login", "number_match", "ttl_seconds", "oidc_login", "client_id"];
const snap = (c) => JSON.stringify(FIELDS.map((k) => (k === "ttl_seconds" ? Number(c[k]) : c[k])));
const MARK = { ok: ["✓", "text-[var(--ok)]"], warn: ["!", "text-[var(--wn,#b7791f)]"], fail: ["✕", "text-[var(--bd)]"] };

const Chip = ({ ok, children }) => (
  <span className={`badge ${ok === true ? "b-ok" : ok === "warn" ? "b-wn" : "b-mu"}`}>{children}</span>
);

function CopyAll({ lines }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(lines.join("\n")); setDone(true); setTimeout(() => setDone(false), 1500); } catch { /* clipboard blocked */ }
  };
  return <button type="button" className="btn btn-g !px-2 !py-1 text-xs" onClick={copy}>{done ? <Check size={13} /> : <Copy size={13} />}{done ? "کپی شد" : "کپی همهٔ آدرس‌ها"}</button>;
}

const USERNAME_RE = /^@?[A-Za-z0-9_]{3,64}$/;

// Main store's bot @username: the deep link t.me/<bot>?start=wl_… cannot be built without it.
function MainBotBox({ saved, call, toast, reload }) {
  const [name, setName] = useState(saved.main_bot_username || "");
  const [busy, setBusy] = useState("");
  const current = saved.main_bot_username || "";
  const typed = name.trim();
  const invalid = typed && !USERNAME_RE.test(typed) ? "فقط حروف انگلیسی، عدد و _ (۳ تا ۶۴ نویسه)." : "";
  const run = async (username, ok) => {
    setBusy(username === null ? "auto" : "save");
    const r = await call("/api/v1/admin/integrations/telegram/main-bot-username", { method: "PUT", body: JSON.stringify({ username }) });
    const d = await r.json().catch(() => ({}));
    setBusy("");
    if (!r.ok) return toast(d?.error?.message || d?.detail?.message || "ذخیرهٔ نام کاربری ربات ناموفق بود");
    toast(ok);
    setName(d.main_bot_username || "");
    reload(d);
  };
  return (
    <div className="space-y-2 rounded-xl border border-[var(--ln)] p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-bold">ربات اصلی فروشگاه</div>
        {current ? <Chip ok><span dir="ltr">@{current}</span></Chip> : <Chip ok="warn">نام کاربری ثبت نشده</Chip>}
      </div>
      {!current && <p className="text-xs leading-6 text-[var(--bd)]">بدون نام کاربری ربات، لینک ورود ساخته نمی‌شود و دکمهٔ «ورود با تلگرام» نمایش داده نمی‌شود.</p>}
      <div className="flex flex-wrap items-start gap-2">
        <button type="button" disabled={!!busy} className="btn" onClick={() => run(null, "نام کاربری ربات از روی توکن تشخیص داده و ذخیره شد")}>{busy === "auto" ? "در حال تشخیص..." : "تشخیص خودکار از توکن"}</button>
        <span className="py-2 text-xs text-[var(--mu)]">یا دستی:</span>
        <div className="min-w-[12rem] flex-1">
          <input dir="ltr" spellCheck={false} autoComplete="off" className="inp font-mono text-xs" value={name} onChange={(e) => setName(e.target.value)} placeholder="@meeloorin_bot" />
          {invalid && <div className="mt-1 text-xs text-[var(--bd)]">{invalid}</div>}
        </div>
        <button type="button" disabled={!!busy || !typed || !!invalid || typed.replace(/^@/, "") === current} className="btn btn-g" onClick={() => run(typed.replace(/^@/, ""), "نام کاربری ربات ذخیره شد")}>{busy === "save" ? "در حال ذخیره..." : "ذخیره نام کاربری"}</button>
      </div>
      <p className="text-xs text-[var(--mu)]">نام کاربری با ربات واقعیِ توکن (getMe) تطبیق داده می‌شود و بلافاصله، بدون build مجدد، اعمال می‌شود. این بخش جدا از دکمهٔ «ذخیره» بالا ذخیره می‌شود.</p>
    </div>
  );
}

function Guide({ cfg }) {
  const ext = (href, text) => <a className="inline-flex items-center gap-1 text-[var(--ac)] underline" href={href} target="_blank" rel="noreferrer noopener">{text} <ExternalLink size={11} /></a>;
  return (
    <details className="group rounded-xl border border-[var(--ln)]">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 p-4 text-sm font-bold">
        <span>راهنمای کامل اتصال تلگرام (گام‌به‌گام)</span>
        <ChevronDown size={16} className="transition group-open:rotate-180" />
      </summary>
      <div className="space-y-6 border-t border-[var(--ln)] p-4 text-sm">
        <div className="space-y-2 rounded-xl bg-[var(--bg)] p-3 text-xs leading-7 text-[var(--mu)]">
          <div className="font-bold text-[var(--tx)]">کدام روش را روشن کنم؟</div>
          <p><b>تأیید در ربات</b> (پیش‌فرض): مشتری روی «ورود با تلگرام» می‌زند، ربات باز می‌شود و ورود را با انتخاب یک عدد تأیید می‌کند. <b>هیچ داده‌ای از BotFather لازم نیست</b>؛ فقط ربات فروشگاه باید فعال باشد. امن‌ترین روش در برابر فیشینگ است (تطبیق عدد + نمایش دستگاه/IP).</p>
          <p><b>ورود مستقیم (OpenID Connect)</b>: مشتری به صفحهٔ رسمی تلگرام می‌رود، با یک «تأیید» برمی‌گردد. سریع‌تر است ولی نیاز به <b>Client ID</b> و <b>Client Secret</b> از BotFather دارد (راهنمای زیر). می‌توانید هر دو را هم‌زمان روشن کنید؛ هر دو به <b>یک حساب</b> مشتری می‌رسند، چون شناسهٔ عددی تلگرام کاربر کلید حساب است.</p>
          <p>ورود <b>ادمین</b> از طریق تلگرام وجود ندارد و عمداً بسته است؛ ادمین فقط با رمز + TOTP وارد می‌شود.</p>
        </div>

        <div>
          <div className="mb-3 font-extrabold">الف) روش «تأیید در ربات» — پیش‌نیازها</div>
          <ul className="list-disc space-y-1.5 pr-5 text-xs leading-7 text-[var(--mu)]">
            <li>توکن ربات اصلی هنگام نصب ثبت شده و سرویس ربات (<code dir="ltr">telegram_main</code>) در حال اجراست؛ نام کاربری ربات روی فروشگاه (<code dir="ltr">bot_username</code>) پر است{cfg.main_bot_username ? <> (الان: <code dir="ltr">@{cfg.main_bot_username}</code>)</> : <> (الان خالی است)</>}.</li>
            <li>ربات‌های نمایندگان خودکار با فروشگاه خودشان کار می‌کنند و تنظیم جدا ندارند.</li>
            <li><b>تطبیق عدد</b> را روشن نگه دارید؛ خاموش‌کردنش فقط برای عیب‌یابی است. «مدت اعتبار» زمانی است که مشتری برای تأیید در ربات دارد (۶۰ تا ۶۰۰ ثانیه، پیش‌فرض ۱۸۰).</li>
            <li>دکمه‌ی «تست اتصال» توکن ربات را با <code dir="ltr">getMe</code> می‌سنجد و نام کاربری را با فروشگاه مقایسه می‌کند.</li>
          </ul>
        </div>

        <div>
          <div className="mb-3 font-extrabold">ب) روش «ورود مستقیم» — راه‌اندازی در BotFather</div>
          <ol className="space-y-5">
            <Step n="۱" title="ربات مناسب را انتخاب کنید">
              <p>معمولاً همان ربات اصلی فروشگاه. کاربر هنگام ورود، <b>نام و عکس همین ربات</b> را در پنجرهٔ تأیید تلگرام می‌بیند؛ برای اعتماد بیشتر نام ربات را برند فروشگاه و عکسش را لوگوی فروشگاه بگذارید.</p>
            </Step>
            <Step n="۲" title="باز کردن تنظیمات ورود در BotFather">
              <p>در تلگرام {ext("https://t.me/botfather?startapp", "مینی‌اپ @BotFather")} را باز کنید (یا از @BotFather روی دکمهٔ Open کنار پیام‌ها بزنید) ← ربات را انتخاب کنید ← <b>Bot Settings ← Web Login</b> (در برخی نسخه‌ها با نام <b>Login Widget</b>) ← اگر پرسید، حالت <b>OpenID Connect</b> را انتخاب کنید.</p>
            </Step>
            <Step n="۳" title="ثبت Allowed URLs">
              <p>تلگرام فقط به آدرس‌هایی که از قبل ثبت شده‌اند اجازهٔ ورود/بازگشت می‌دهد. <b>همه‌ی آدرس‌های زیر</b> را (هر کدام یک ردیف) در بخش <b>Allowed URLs</b> اضافه کنید؛ دقیقاً به همین شکل، با https و بدون «/» پایانی. اگر نماینده‌ای دامنهٔ اختصاصی دارد، آدرس آن هم در فهرست آمده است و باید ثبت شود.</p>
              <div className="space-y-1.5">{[...cfg.origins, ...cfg.redirect_uris].map((u) => <CopyBox key={u} text={u} />)}</div>
            </Step>
            <Step n="۴" title="کپی Client ID و Client Secret">
              <p>در همان صفحه BotFather مقدار <b>Client ID</b> و <b>Client Secret</b> را نشان می‌دهد. Client ID یک <b>عدد</b> است و همان شناسهٔ ربات است (عدد قبل از «:» در توکن ربات). Client Secret را جایی عمومی نفرستید.</p>
              <p><b>الگوریتم امضا</b> را روی پیش‌فرض <code dir="ltr">RS256</code> (یا <code dir="ltr">ES256</code>) نگه دارید. <code dir="ltr">EdDSA</code> و <code dir="ltr">ES256K</code> فقط scope پایه می‌دهند و شناسهٔ کاربر را برنمی‌گردانند؛ ورود با آن‌ها کار نمی‌کند.</p>
            </Step>
            <Step n="۵" title="ثبت در ملورین">
              <p>«ورود مستقیم» را روشن کنید، Client ID و Client Secret را در فیلدهای بالا بچسبانید و <b>ذخیره</b> کنید. Secret رمزنگاری‌شده ذخیره می‌شود و دیگر نمایش داده نمی‌شود (برای تغییر، مقدار جدید را وارد کنید). سپس <b>تست اتصال</b> را بزنید.</p>
            </Step>
            <Step n="۶" title="آزمایش ورود واقعی">
              <p>در یک پنجرهٔ ناشناس به فروشگاه بروید ← «ورود» ← «ورود مستقیم با تلگرام». پس از تأیید در تلگرام به داشبورد برمی‌گردید. نخستین بار حساب مشتری ساخته می‌شود؛ ثبت‌نام بسته (پرچم <code dir="ltr">registration</code>) فقط حساب‌های جدید را رد می‌کند.</p>
              <p>ملورین فقط scopeهای <code dir="ltr">openid profile</code> را می‌خواهد (نام، نام‌کاربری، شناسه). شمارهٔ تلفن درخواست <b>نمی‌شود</b>.</p>
            </Step>
          </ol>
        </div>

        <div className="rounded-xl border border-[var(--ln)] p-3">
          <div className="mb-2 flex items-center gap-2 font-bold"><ShieldCheck size={16} />عیب‌یابی</div>
          <ul className="list-disc space-y-1.5 pr-5 text-xs leading-7 text-[var(--mu)]">
            <li>تلگرام خطای «redirect/URL not allowed» می‌دهد: آدرس بازگشت (ردیف‌های <code dir="ltr">…/callback</code>) یا origin در Allowed URLs نیست یا با آن تفاوت جزئی دارد (http/https، www، «/» پایانی).</li>
            <li>پس از برگشت، پیام «نشست ورود منقضی شد» (<code dir="ltr">session_expired</code>): بیش از ۱۰ دقیقه گذشته، کوکی‌ها در مرورگر بسته‌اند، یا شروع ورود و بازگشت روی دو دامنهٔ متفاوت (مثلاً www و بدون www) بوده است.</li>
            <li><code dir="ltr">origin_mismatch</code>: دامنه‌ای که مشتری با آن آمده با <code dir="ltr">MELORIN_STORE_WEB_URL</code> (یا دامنهٔ نماینده) یکی نیست. همان دامنه را در <code dir="ltr">.env</code> اصلاح کنید.</li>
            <li>پیام «ورود انجام نشد» (<code dir="ltr">failed</code>) بعد از تأیید: Client Secret اشتباه یا قدیمی است (در BotFather دوباره بسازید و اینجا ذخیره کنید)، Client ID با ربات هم‌خوان نیست، یا الگوریتم امضا EdDSA/ES256K است. «تست اتصال» را بزنید.</li>
            <li>تست اتصال ناموفق: سرور API باید به <code dir="ltr">oauth.telegram.org</code> و <code dir="ltr">api.telegram.org</code> روی پورت ۴۴۳ خروجی داشته باشد (فایروال، DNS یا فیلترینگ شبکهٔ سرور را بررسی کنید).</li>
            <li>مرورگر مشتری هم باید به <code dir="ltr">oauth.telegram.org</code> برسد. اگر در شبکهٔ مشتری باز نمی‌شود، روش «تأیید در ربات» را روشن نگه دارید؛ آن روش فقط به خود اپ تلگرام نیاز دارد.</li>
            <li><code dir="ltr">admin_use_panel</code>: حساب تلگرامی که وارد شده به یک ادمین وصل است؛ ادمین‌ها فقط از پنل مدیریت وارد می‌شوند. <code dir="ltr">account_disabled</code>: حساب مشتری غیرفعال است.</li>
            <li>دکمه‌ی ورود نمایش داده نمی‌شود: کلید اصلی یا «ورود مشتریان» خاموش است، روش مربوط روشن نیست، یا (برای ورود مستقیم) Client ID/Secret ذخیره نشده است. تغییرات بدون build مجدد اعمال می‌شود.</li>
          </ul>
        </div>
      </div>
    </details>
  );
}

export default function TelegramLoginSettings({ api, toast }) {
  const call = (p, o = {}) => authFetch(api.base, p, o);
  const [cfg, setCfg] = useState(null);
  const [saved, setSaved] = useState(null); // the server's copy: badges and the connection test describe THIS, not the unsaved form
  const [secret, setSecret] = useState("");
  const [clearSecret, setClearSecret] = useState(false);
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState(null);

  const load = () => call("/api/v1/admin/integrations")
    .then((r) => (r.ok ? r.json() : Promise.reject()))
    .then((d) => { setCfg(d.telegram); setSaved(d.telegram); setSecret(""); setClearSecret(false); })
    .catch(() => toast("دریافت تنظیمات تلگرام ناموفق بود"));
  useEffect(() => { load(); }, []);
  // After the bot username changes keep the admin's unsaved form edits: only refresh the server copy.
  const reloadBot = (t) => { setSaved(t); setCfg((c) => ({ ...c, main_bot_username: t.main_bot_username })); setResult(null); };

  if (!cfg || !saved) return null;

  const id = (cfg.client_id || "").trim();
  const idError = id && !CLIENT_ID_RE.test(id) ? "Client ID فقط عدد است (شناسهٔ عددی ربات)." : "";
  const ttl = Number(cfg.ttl_seconds);
  const ttlError = cfg.bot_login && !(Number.isInteger(ttl) && ttl >= cfg.ttl_min && ttl <= cfg.ttl_max) ? `عددی صحیح بین ${cfg.ttl_min} و ${cfg.ttl_max} وارد کنید.` : "";
  const hasSecret = (cfg.client_secret_set && !clearSecret) || !!secret.trim();
  const oidcOk = !cfg.oidc_login || (id && !idError && hasSecret);
  const canSave = !idError && !ttlError && (!cfg.enabled || ((cfg.bot_login || cfg.oidc_login) && oidcOk));
  const dirty = !!saved && (snap(cfg) !== snap(saved) || !!secret.trim() || clearSecret);
  const set = (k) => (v) => { setCfg({ ...cfg, [k]: v }); setResult(null); };
  // What the storefront really does right now (mirrors the server's public_telegram()): from the SAVED copy.
  const botReady = !!(saved.enabled && saved.store_login && saved.bot_login && saved.main_bot_username);
  const oidcReady = !!(saved.enabled && saved.store_login && saved.oidc_login && saved.client_id && saved.client_secret_set);
  const live = botReady || oidcReady;

  const save = async () => {
    setBusy("save");
    const body = {
      enabled: cfg.enabled, store_login: cfg.store_login, bot_login: cfg.bot_login, number_match: cfg.number_match,
      ttl_seconds: Number(cfg.ttl_seconds) || 180, oidc_login: cfg.oidc_login, client_id: id,
      client_secret: secret.trim() ? secret.trim() : clearSecret ? "" : null,
    };
    const r = await call("/api/v1/admin/integrations/telegram", { method: "PUT", body: JSON.stringify(body) });
    const d = await r.json().catch(() => ({}));
    setBusy("");
    if (!r.ok) return toast(d?.error?.message || d?.detail?.message || "ذخیره ناموفق بود");
    toast("تنظیمات ورود با تلگرام ذخیره شد");
    setResult(null);
    load();
  };
  const test = async () => {
    setBusy("test");
    const r = await call("/api/v1/admin/integrations/telegram/test", { method: "POST", body: "{}" });
    const d = await r.json().catch(() => ({}));
    setBusy("");
    setResult(r.ok ? d : { ok: false, checks: [{ key: "x", status: "fail", message: d?.error?.message || "تست انجام نشد" }] });
  };

  const sourceLabel = cfg.source === "panel" ? "ذخیره‌شده در پنل" : "پیش‌فرض (هنوز در پنل ذخیره نشده؛ روش تأیید در ربات فعال است)";
  return (
    <section className="card space-y-5 p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 font-extrabold"><Send size={16} />ورود با تلگرام <span className="text-xs font-normal text-[var(--mu)]">(اختیاری)</span></h3>
        <span className={`badge ${live ? "b-ok" : "b-mu"}`}>{live ? "فعال" : "غیرفعال"}</span>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs" aria-label="وضعیت روش‌ها (ذخیره‌شده)">
        <span className="font-bold text-[var(--mu)]">روش ۱ · تأیید در ربات:</span>
        {botReady ? <Chip ok>آماده</Chip> : saved.bot_login && saved.enabled && saved.store_login ? <Chip ok="warn">نام کاربری ربات فروشگاه تنظیم نشده</Chip> : <Chip>خاموش</Chip>}
        <span className="mr-2 font-bold text-[var(--mu)]">روش ۲ · ورود مستقیم:</span>
        {oidcReady ? <Chip ok>آماده</Chip> : saved.oidc_login && saved.enabled && saved.store_login ? <Chip ok="warn">Client ID/Secret ناقص</Chip> : <Chip>خاموش</Chip>}
      </div>
      <p className="text-xs leading-7 text-[var(--mu)]">منبع تنظیم فعلی: {sourceLabel}. تغییرات بلافاصله و بدون build مجدد در فروشگاه اعمال می‌شود. ورود ادمین با تلگرام وجود ندارد.</p>

      <div className="grid gap-3 md:grid-cols-2">
        <Switch on={cfg.enabled} set={set("enabled")} label="فعال‌سازی ورود با تلگرام" hint="کلید اصلی؛ با خاموش بودن، هیچ دکمهٔ تلگرامی در فروشگاه نمایش داده نمی‌شود و درخواست‌های باز بسته می‌شوند." />
        <Switch on={cfg.store_login} set={set("store_login")} label="ورود مشتریان (فروشگاه)" hint="دکمه‌های تلگرام در پنجرهٔ ورود فروشگاه." />
        <Switch on={cfg.bot_login} set={set("bot_login")} label="روش ۱: تأیید در ربات" hint="بدون داده‌ی اضافه؛ با تطبیق عدد و نمایش دستگاه/IP." />
        <Switch on={cfg.oidc_login} set={set("oidc_login")} label="روش ۲: ورود مستقیم (OpenID Connect)" hint="نیازمند Client ID و Client Secret از BotFather." />
      </div>

      {cfg.bot_login && (
        <div className="space-y-3 rounded-xl border border-[var(--ln)] p-4">
          <div className="text-sm font-bold">تنظیمات روش «تأیید در ربات»</div>
          <div className="grid gap-3 md:grid-cols-2">
            <Switch on={cfg.number_match} set={set("number_match")} label="تطبیق عدد (توصیه‌شده)" hint="مشتری باید همان عدد نمایش‌داده‌شده در سایت را در ربات انتخاب کند؛ ضدفیشینگ." />
            <Field label="مدت اعتبار درخواست (ثانیه)" error={ttlError} hint={`بین ${cfg.ttl_min} و ${cfg.ttl_max}. پیش‌فرض ۱۸۰.`}>
              <input dir="ltr" type="number" min={cfg.ttl_min} max={cfg.ttl_max} className="inp font-mono text-xs" value={cfg.ttl_seconds} onChange={(e) => set("ttl_seconds")(e.target.value)} />
            </Field>
          </div>
          <MainBotBox key={saved.main_bot_username || "none"} saved={saved} call={call} toast={toast} reload={reloadBot} />
        </div>
      )}

      {cfg.oidc_login && (
        <div className="space-y-4 rounded-xl border border-[var(--ln)] p-4">
          <div className="text-sm font-bold">اطلاعات «ورود مستقیم» (از BotFather ← Bot Settings ← Web Login)</div>
          <Field label="Client ID (شناسهٔ عددی ربات)" error={idError} hint="فقط عدد؛ همان عدد قبل از «:» در توکن ربات.">
            <input dir="ltr" inputMode="numeric" spellCheck={false} autoComplete="off" className="inp font-mono text-xs" value={cfg.client_id} onChange={(e) => set("client_id")(e.target.value)} placeholder="123456789" />
            {cfg.suggested_client_id && cfg.suggested_client_id !== id && (
              <button type="button" className="btn btn-g mt-2 !px-2 !py-1 text-xs" onClick={() => set("client_id")(cfg.suggested_client_id)}>استفاده از شناسهٔ ربات اصلی ({cfg.suggested_client_id})</button>
            )}
          </Field>
          <Field label="Client Secret" hint={cfg.client_secret_set && !clearSecret ? "یک Secret ذخیره شده است و نمایش داده نمی‌شود. برای تغییر، مقدار جدید را وارد کنید." : "از همان صفحهٔ BotFather کپی کنید. رمزنگاری‌شده ذخیره می‌شود."}>
            <input dir="ltr" type="password" spellCheck={false} autoComplete="new-password" className="inp font-mono text-xs" value={secret} onChange={(e) => { setSecret(e.target.value); setClearSecret(false); setResult(null); }} placeholder={cfg.client_secret_set && !clearSecret ? "••••••••••••• (ذخیره‌شده)" : "Client Secret"} />
            {cfg.client_secret_set && (
              <label className="mt-2 flex cursor-pointer items-center gap-2 text-xs font-normal"><input type="checkbox" checked={clearSecret} onChange={(e) => { setClearSecret(e.target.checked); if (e.target.checked) setSecret(""); }} />حذف Secret ذخیره‌شده</label>
            )}
          </Field>
          <div className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2"><div className="text-xs font-bold text-[var(--mu)]">Allowed URLs که باید در BotFather ثبت شوند (هر ردیف جدا)</div><CopyAll lines={[...cfg.origins, ...cfg.redirect_uris]} /></div>
            <div className="grid gap-1.5 md:grid-cols-2">{[...cfg.origins, ...cfg.redirect_uris].map((u) => <CopyBox key={u} text={u} />)}</div>
            <p className="text-xs text-[var(--mu)]">هم آدرس سایت (origin) و هم آدرس بازگشت (<code dir="ltr">/callback</code>) را ثبت کنید. دامنهٔ هر نمایندهٔ فعال هم در فهرست آمده است.</p>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button disabled={busy === "save" || !canSave || (!dirty && saved.source === "panel")} className="btn" onClick={save}>{busy === "save" ? "در حال ذخیره..." : "ذخیره"}</button>
        <button disabled={busy === "test" || dirty} title={dirty ? "ابتدا تغییرات را ذخیره کنید" : undefined} className="btn btn-g" onClick={test}>{busy === "test" ? "در حال تست..." : "تست اتصال"}</button>
        {dirty && <span className="text-xs font-bold text-[var(--wn,#b7791f)]">تغییرات ذخیره‌نشده</span>}
        {!canSave && cfg.enabled && <span className="text-xs text-[var(--bd)]">{ttlError || idError || (!(cfg.bot_login || cfg.oidc_login) ? "حداقل یک روش را روشن کنید." : "برای ورود مستقیم، Client ID و Client Secret لازم است.")}</span>}
      </div>
      {result && (
        <ul className="space-y-1.5 rounded-xl border border-[var(--ln)] p-3 text-xs leading-6">
          {result.checks.map((c) => { const [m, cls] = MARK[c.status] || MARK.warn; return <li key={c.key} className="flex gap-2"><b className={`w-4 shrink-0 text-center ${cls}`}>{m}</b><span>{c.message}</span></li>; })}
        </ul>
      )}
      <p className="text-xs text-[var(--mu)]">«تست اتصال» روی مقدار <b>ذخیره‌شده</b> کار می‌کند؛ ابتدا ذخیره کنید. درستیِ Allowed URLs فقط با یک ورود واقعی مشخص می‌شود.</p>

      <Guide cfg={cfg} />
    </section>
  );
}
