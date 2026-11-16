import type { ReactNode } from 'react';
import { useState } from 'react';
import { settled, typedClient } from '../../api/api.ts';
import { Check, ChevronDown, Copy, ExternalLink, ShieldCheck } from 'lucide-react';
import { CopyBox, Step } from './GoogleLoginSettings.tsx';
import type { Json, Toast } from '../../shared/types.ts';

export const Chip = ({ ok, children }: { ok?: Json; children?: ReactNode }) => (
  <span className={`badge ${ok === true ? 'b-ok' : ok === 'warn' ? 'b-wn' : 'b-mu'}`}>{children}</span>
);

export function CopyAll({ lines }: { lines?: Json }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(lines.join('\n'));
      setDone(true);
      setTimeout(() => setDone(false), 1500);
    } catch {
      /* clipboard blocked */
    }
  };
  return (
    <button type="button" className="btn btn-g !px-2 !py-1 text-xs" onClick={copy}>
      {done ? <Check size={13} /> : <Copy size={13} />}
      {done ? 'کپی شد' : 'کپی همهٔ آدرس‌ها'}
    </button>
  );
}

export const USERNAME_RE = /^@?[A-Za-z0-9_]{3,64}$/;

// Main store's bot @username: the deep link t.me/<bot>?start=wl_… cannot be built without it.
export function MainBotBox({
  saved,
  base,
  toast,
  reload,
}: {
  saved?: Json;
  base: string;
  toast: Toast;
  reload?: Json;
}) {
  const [name, setName] = useState(saved.main_bot_username || '');
  const [busy, setBusy] = useState('');
  const current = saved.main_bot_username || '';
  const typed = name.trim();
  const invalid = typed && !USERNAME_RE.test(typed) ? 'فقط حروف انگلیسی، عدد و _ (۳ تا ۶۴ نویسه).' : '';
  const run = async (username: Json, ok: Json) => {
    setBusy(username === null ? 'auto' : 'save');
    const { r, d } = settled(
      await typedClient(base).put('/api/v1/admin/integrations/telegram/main-bot-username', { body: { username } }),
    );
    setBusy('');
    if (!r.ok) return toast(d?.error?.message || d?.detail?.message || 'ذخیرهٔ نام کاربری ربات ناموفق بود');
    toast(ok);
    setName(d.main_bot_username || '');
    reload(d);
  };
  return (
    <div className="space-y-2 rounded-xl border border-[var(--ln)] p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-bold">ربات اصلی فروشگاه</div>
        {current ? (
          <Chip ok>
            <span dir="ltr">@{current}</span>
          </Chip>
        ) : (
          <Chip ok="warn">نام کاربری ثبت نشده</Chip>
        )}
      </div>
      {!current && (
        <p className="text-xs leading-6 text-[var(--bd)]">
          بدون نام کاربری ربات، لینک ورود ساخته نمی‌شود و دکمهٔ «ورود با تلگرام» نمایش داده نمی‌شود.
        </p>
      )}
      <div className="flex flex-wrap items-start gap-2">
        <button
          type="button"
          disabled={!!busy}
          className="btn"
          onClick={() => run(null, 'نام کاربری ربات از روی توکن تشخیص داده و ذخیره شد')}
        >
          {busy === 'auto' ? 'در حال تشخیص...' : 'تشخیص خودکار از توکن'}
        </button>
        <span className="py-2 text-xs text-[var(--mu)]">یا دستی:</span>
        <div className="min-w-[12rem] flex-1">
          <input
            dir="ltr"
            spellCheck={false}
            autoComplete="off"
            className="inp font-mono text-xs"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="@meeloorin_bot"
          />
          {invalid && <div className="mt-1 text-xs text-[var(--bd)]">{invalid}</div>}
        </div>
        <button
          type="button"
          disabled={!!busy || !typed || !!invalid || typed.replace(/^@/, '') === current}
          className="btn btn-g"
          onClick={() => run(typed.replace(/^@/, ''), 'نام کاربری ربات ذخیره شد')}
        >
          {busy === 'save' ? 'در حال ذخیره...' : 'ذخیره نام کاربری'}
        </button>
      </div>
      <p className="text-xs text-[var(--mu)]">
        نام کاربری با ربات واقعیِ توکن (getMe) تطبیق داده می‌شود و بلافاصله، بدون build مجدد، اعمال می‌شود. این بخش جدا
        از دکمهٔ «ذخیره» بالا ذخیره می‌شود.
      </p>
    </div>
  );
}

export function Guide({ cfg }: { cfg?: Json }) {
  const ext = (href: string, text: Json) => (
    <a
      className="inline-flex items-center gap-1 text-[var(--ac)] underline"
      href={href}
      target="_blank"
      rel="noreferrer noopener"
    >
      {text} <ExternalLink size={11} />
    </a>
  );
  return (
    <details className="group rounded-xl border border-[var(--ln)]">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 p-4 text-sm font-bold">
        <span>راهنمای کامل اتصال تلگرام (گام‌به‌گام)</span>
        <ChevronDown size={16} className="transition group-open:rotate-180" />
      </summary>
      <div className="space-y-6 border-t border-[var(--ln)] p-4 text-sm">
        <div className="space-y-2 rounded-xl bg-[var(--bg)] p-3 text-xs leading-7 text-[var(--mu)]">
          <div className="font-bold text-[var(--tx)]">کدام روش را روشن کنم؟</div>
          <p>
            <b>تأیید در ربات</b> (پیش‌فرض): مشتری روی «ورود با تلگرام» می‌زند، ربات باز می‌شود و ورود را با انتخاب یک
            عدد تأیید می‌کند. <b>هیچ داده‌ای از BotFather لازم نیست</b>؛ فقط ربات فروشگاه باید فعال باشد. امن‌ترین روش
            در برابر فیشینگ است (تطبیق عدد + نمایش دستگاه/IP).
          </p>
          <p>
            <b>ورود مستقیم (OpenID Connect)</b>: مشتری به صفحهٔ رسمی تلگرام می‌رود، با یک «تأیید» برمی‌گردد. سریع‌تر است
            ولی نیاز به <b>Client ID</b> و <b>Client Secret</b> از BotFather دارد (راهنمای زیر). می‌توانید هر دو را
            هم‌زمان روشن کنید؛ هر دو به <b>یک حساب</b> مشتری می‌رسند، چون شناسهٔ عددی تلگرام کاربر کلید حساب است.
          </p>
          <p>
            ورود <b>ادمین</b> از طریق تلگرام وجود ندارد و عمداً بسته است؛ ادمین فقط با رمز + TOTP وارد می‌شود.
          </p>
        </div>

        <div>
          <div className="mb-3 font-extrabold">الف) روش «تأیید در ربات» — پیش‌نیازها</div>
          <ul className="list-disc space-y-1.5 pr-5 text-xs leading-7 text-[var(--mu)]">
            <li>
              توکن ربات اصلی هنگام نصب ثبت شده و سرویس ربات (<code dir="ltr">telegram_main</code>) در حال اجراست؛ نام
              کاربری ربات روی فروشگاه (<code dir="ltr">bot_username</code>) پر است
              {cfg.main_bot_username ? (
                <>
                  {' '}
                  (الان: <code dir="ltr">@{cfg.main_bot_username}</code>)
                </>
              ) : (
                <> (الان خالی است)</>
              )}
              .
            </li>
            <li>ربات‌های نمایندگان خودکار با فروشگاه خودشان کار می‌کنند و تنظیم جدا ندارند.</li>
            <li>
              <b>تطبیق عدد</b> را روشن نگه دارید؛ خاموش‌کردنش فقط برای عیب‌یابی است. «مدت اعتبار» زمانی است که مشتری
              برای تأیید در ربات دارد (۶۰ تا ۶۰۰ ثانیه، پیش‌فرض ۱۸۰).
            </li>
            <li>
              دکمه‌ی «تست اتصال» توکن ربات را با <code dir="ltr">getMe</code> می‌سنجد و نام کاربری را با فروشگاه مقایسه
              می‌کند.
            </li>
          </ul>
        </div>

        <div>
          <div className="mb-3 font-extrabold">ب) روش «ورود مستقیم» — راه‌اندازی در BotFather</div>
          <ol className="space-y-5">
            <Step n="۱" title="ربات مناسب را انتخاب کنید">
              <p>
                معمولاً همان ربات اصلی فروشگاه. کاربر هنگام ورود، <b>نام و عکس همین ربات</b> را در پنجرهٔ تأیید تلگرام
                می‌بیند؛ برای اعتماد بیشتر نام ربات را برند فروشگاه و عکسش را لوگوی فروشگاه بگذارید.
              </p>
            </Step>
            <Step n="۲" title="باز کردن تنظیمات ورود در BotFather">
              <p>
                در تلگرام {ext('https://t.me/botfather?startapp', 'مینی‌اپ @BotFather')} را باز کنید (یا از @BotFather
                روی دکمهٔ Open کنار پیام‌ها بزنید) ← ربات را انتخاب کنید ← <b>Bot Settings ← Web Login</b> (در برخی
                نسخه‌ها با نام <b>Login Widget</b>) ← اگر پرسید، حالت <b>OpenID Connect</b> را انتخاب کنید.
              </p>
            </Step>
            <Step n="۳" title="ثبت Allowed URLs">
              <p>
                تلگرام فقط به آدرس‌هایی که از قبل ثبت شده‌اند اجازهٔ ورود/بازگشت می‌دهد. <b>همه‌ی آدرس‌های زیر</b> را
                (هر کدام یک ردیف) در بخش <b>Allowed URLs</b> اضافه کنید؛ دقیقاً به همین شکل، با https و بدون «/» پایانی.
                اگر نماینده‌ای دامنهٔ اختصاصی دارد، آدرس آن هم در فهرست آمده است و باید ثبت شود.
              </p>
              <div className="space-y-1.5">
                {[...cfg.origins, ...cfg.redirect_uris].map((u) => (
                  <CopyBox key={u} text={u} />
                ))}
              </div>
            </Step>
            <Step n="۴" title="کپی Client ID و Client Secret">
              <p>
                در همان صفحه BotFather مقدار <b>Client ID</b> و <b>Client Secret</b> را نشان می‌دهد. Client ID یک{' '}
                <b>عدد</b> است و همان شناسهٔ ربات است (عدد قبل از «:» در توکن ربات). Client Secret را جایی عمومی
                نفرستید.
              </p>
              <p>
                <b>الگوریتم امضا</b> را روی پیش‌فرض <code dir="ltr">RS256</code> (یا <code dir="ltr">ES256</code>) نگه
                دارید. <code dir="ltr">EdDSA</code> و <code dir="ltr">ES256K</code> فقط scope پایه می‌دهند و شناسهٔ
                کاربر را برنمی‌گردانند؛ ورود با آن‌ها کار نمی‌کند.
              </p>
            </Step>
            <Step n="۵" title="ثبت در ملورین">
              <p>
                «ورود مستقیم» را روشن کنید، Client ID و Client Secret را در فیلدهای بالا بچسبانید و <b>ذخیره</b> کنید.
                Secret رمزنگاری‌شده ذخیره می‌شود و دیگر نمایش داده نمی‌شود (برای تغییر، مقدار جدید را وارد کنید). سپس{' '}
                <b>تست اتصال</b> را بزنید.
              </p>
            </Step>
            <Step n="۶" title="آزمایش ورود واقعی">
              <p>
                در یک پنجرهٔ ناشناس به فروشگاه بروید ← «ورود» ← «ورود مستقیم با تلگرام». پس از تأیید در تلگرام به
                داشبورد برمی‌گردید. نخستین بار حساب مشتری ساخته می‌شود؛ ثبت‌نام بسته (پرچم{' '}
                <code dir="ltr">registration</code>) فقط حساب‌های جدید را رد می‌کند.
              </p>
              <p>
                ملورین فقط scopeهای <code dir="ltr">openid profile</code> را می‌خواهد (نام، نام‌کاربری، شناسه). شمارهٔ
                تلفن درخواست <b>نمی‌شود</b>.
              </p>
            </Step>
          </ol>
        </div>

        <div className="rounded-xl border border-[var(--ln)] p-3">
          <div className="mb-2 flex items-center gap-2 font-bold">
            <ShieldCheck size={16} />
            عیب‌یابی
          </div>
          <ul className="list-disc space-y-1.5 pr-5 text-xs leading-7 text-[var(--mu)]">
            <li>
              تلگرام خطای «redirect/URL not allowed» می‌دهد: آدرس بازگشت (ردیف‌های <code dir="ltr">…/callback</code>) یا
              origin در Allowed URLs نیست یا با آن تفاوت جزئی دارد (http/https، www، «/» پایانی).
            </li>
            <li>
              پس از برگشت، پیام «نشست ورود منقضی شد» (<code dir="ltr">session_expired</code>): بیش از ۱۰ دقیقه گذشته،
              کوکی‌ها در مرورگر بسته‌اند، یا شروع ورود و بازگشت روی دو دامنهٔ متفاوت (مثلاً www و بدون www) بوده است.
            </li>
            <li>
              <code dir="ltr">origin_mismatch</code>: دامنه‌ای که مشتری با آن آمده با{' '}
              <code dir="ltr">MELORIN_STORE_WEB_URL</code> (یا دامنهٔ نماینده) یکی نیست. همان دامنه را در{' '}
              <code dir="ltr">.env</code> اصلاح کنید.
            </li>
            <li>
              پیام «ورود انجام نشد» (<code dir="ltr">failed</code>) بعد از تأیید: Client Secret اشتباه یا قدیمی است (در
              BotFather دوباره بسازید و اینجا ذخیره کنید)، Client ID با ربات هم‌خوان نیست، یا الگوریتم امضا EdDSA/ES256K
              است. «تست اتصال» را بزنید.
            </li>
            <li>
              تست اتصال ناموفق: سرور API باید به <code dir="ltr">oauth.telegram.org</code> و{' '}
              <code dir="ltr">api.telegram.org</code> روی پورت ۴۴۳ خروجی داشته باشد (فایروال، DNS یا فیلترینگ شبکهٔ سرور
              را بررسی کنید).
            </li>
            <li>
              مرورگر مشتری هم باید به <code dir="ltr">oauth.telegram.org</code> برسد. اگر در شبکهٔ مشتری باز نمی‌شود،
              روش «تأیید در ربات» را روشن نگه دارید؛ آن روش فقط به خود اپ تلگرام نیاز دارد.
            </li>
            <li>
              <code dir="ltr">admin_use_panel</code>: حساب تلگرامی که وارد شده به یک ادمین وصل است؛ ادمین‌ها فقط از پنل
              مدیریت وارد می‌شوند. <code dir="ltr">account_disabled</code>: حساب مشتری غیرفعال است.
            </li>
            <li>
              دکمه‌ی ورود نمایش داده نمی‌شود: کلید اصلی یا «ورود مشتریان» خاموش است، روش مربوط روشن نیست، یا (برای ورود
              مستقیم) Client ID/Secret ذخیره نشده است. تغییرات بدون build مجدد اعمال می‌شود.
            </li>
          </ul>
        </div>
      </div>
    </details>
  );
}
