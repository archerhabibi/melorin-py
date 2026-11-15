import { useEffect, useState } from 'react';
import { settled, typedClient } from '../../api/api.ts';
import { Send } from 'lucide-react';
import { CopyBox, Field, Switch } from './GoogleLoginSettings.tsx';
import { PasswordInput } from '../../shared/ui.tsx';
import type { Json, Rec, Toast } from '../../shared/types.ts';
import { Chip, CopyAll, MainBotBox, Guide } from './TelegramLoginParts.tsx';

const CLIENT_ID_RE = /^[0-9]{5,20}$/;
const FIELDS = ['enabled', 'store_login', 'bot_login', 'number_match', 'ttl_seconds', 'oidc_login', 'client_id'];
const snap = (c: Json) => JSON.stringify(FIELDS.map((k) => (k === 'ttl_seconds' ? Number(c[k]) : c[k])));
const MARK: Rec = {
  ok: ['✓', 'text-[var(--ok)]'],
  warn: ['!', 'text-[var(--wn,#b7791f)]'],
  fail: ['✕', 'text-[var(--bd)]'],
};

export default function TelegramLoginSettings({ api, toast }: { api?: Json; toast: Toast }) {
  const [cfg, setCfg] = useState<Json>(null);
  const [saved, setSaved] = useState<Json>(null); // the server's copy: badges and the connection test describe THIS, not the unsaved form
  const [secret, setSecret] = useState('');
  const [clearSecret, setClearSecret] = useState(false);
  const [busy, setBusy] = useState('');
  const [result, setResult] = useState<Json>(null);

  const load = () =>
    typedClient(api.base)
      .get('/api/v1/admin/integrations')
      .then(({ response: r, data }) => (r.ok ? (data as Json) : Promise.reject()))
      .then((d) => {
        setCfg(d.telegram);
        setSaved(d.telegram);
        setSecret('');
        setClearSecret(false);
      })
      .catch(() => toast('دریافت تنظیمات تلگرام ناموفق بود'));
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- T-W08: reviewed, dependency list intentionally limited (adding the flagged value risks refetch loops); verify in a browser before changing
  }, []);
  // After the bot username changes keep the admin's unsaved form edits: only refresh the server copy.
  const reloadBot = (t: Json) => {
    setSaved(t);
    setCfg((c: Json) => ({ ...c, main_bot_username: t.main_bot_username }));
    setResult(null);
  };

  if (!cfg || !saved) return null;

  const id = (cfg.client_id || '').trim();
  const idError = id && !CLIENT_ID_RE.test(id) ? 'Client ID فقط عدد است (شناسهٔ عددی ربات).' : '';
  const ttl = Number(cfg.ttl_seconds);
  const ttlError =
    cfg.bot_login && !(Number.isInteger(ttl) && ttl >= cfg.ttl_min && ttl <= cfg.ttl_max)
      ? `عددی صحیح بین ${cfg.ttl_min} و ${cfg.ttl_max} وارد کنید.`
      : '';
  const hasSecret = (cfg.client_secret_set && !clearSecret) || !!secret.trim();
  const oidcOk = !cfg.oidc_login || (id && !idError && hasSecret);
  const canSave = !idError && !ttlError && (!cfg.enabled || ((cfg.bot_login || cfg.oidc_login) && oidcOk));
  const dirty = !!saved && (snap(cfg) !== snap(saved) || !!secret.trim() || clearSecret);
  const set = (k: Json) => (v: Json) => {
    setCfg({ ...cfg, [k]: v });
    setResult(null);
  };
  // What the storefront really does right now (mirrors the server's public_telegram()): from the SAVED copy.
  const botReady = !!(saved.enabled && saved.store_login && saved.bot_login && saved.main_bot_username);
  const oidcReady = !!(
    saved.enabled &&
    saved.store_login &&
    saved.oidc_login &&
    saved.client_id &&
    saved.client_secret_set
  );
  const live = botReady || oidcReady;

  const save = async () => {
    setBusy('save');
    const body = {
      enabled: cfg.enabled,
      store_login: cfg.store_login,
      bot_login: cfg.bot_login,
      number_match: cfg.number_match,
      ttl_seconds: Number(cfg.ttl_seconds) || 180,
      oidc_login: cfg.oidc_login,
      client_id: id,
      client_secret: secret.trim() ? secret.trim() : clearSecret ? '' : null,
    };
    const { r, d } = settled(await typedClient(api.base).put('/api/v1/admin/integrations/telegram', { body }));
    setBusy('');
    if (!r.ok) return toast(d?.error?.message || d?.detail?.message || 'ذخیره ناموفق بود');
    toast('تنظیمات ورود با تلگرام ذخیره شد');
    setResult(null);
    load();
  };
  const test = async () => {
    setBusy('test');
    const { r, d } = settled(
      await typedClient(api.base).post('/api/v1/admin/integrations/telegram/test', { body: {} }),
    );
    setBusy('');
    setResult(
      r.ok ? d : { ok: false, checks: [{ key: 'x', status: 'fail', message: d?.error?.message || 'تست انجام نشد' }] },
    );
  };

  const sourceLabel =
    cfg.source === 'panel' ? 'ذخیره‌شده در پنل' : 'پیش‌فرض (هنوز در پنل ذخیره نشده؛ روش تأیید در ربات فعال است)';
  return (
    <section className="card space-y-5 p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 font-extrabold">
          <Send size={16} />
          ورود با تلگرام <span className="text-xs font-normal text-[var(--mu)]">(اختیاری)</span>
        </h3>
        <span className={`badge ${live ? 'b-ok' : 'b-mu'}`}>{live ? 'فعال' : 'غیرفعال'}</span>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs" aria-label="وضعیت روش‌ها (ذخیره‌شده)">
        <span className="font-bold text-[var(--mu)]">روش ۱ · تأیید در ربات:</span>
        {botReady ? (
          <Chip ok>آماده</Chip>
        ) : saved.bot_login && saved.enabled && saved.store_login ? (
          <Chip ok="warn">نام کاربری ربات فروشگاه تنظیم نشده</Chip>
        ) : (
          <Chip>خاموش</Chip>
        )}
        <span className="mr-2 font-bold text-[var(--mu)]">روش ۲ · ورود مستقیم:</span>
        {oidcReady ? (
          <Chip ok>آماده</Chip>
        ) : saved.oidc_login && saved.enabled && saved.store_login ? (
          <Chip ok="warn">Client ID/Secret ناقص</Chip>
        ) : (
          <Chip>خاموش</Chip>
        )}
      </div>
      <p className="text-xs leading-7 text-[var(--mu)]">
        منبع تنظیم فعلی: {sourceLabel}. تغییرات بلافاصله و بدون build مجدد در فروشگاه اعمال می‌شود. ورود ادمین با تلگرام
        وجود ندارد.
      </p>

      <div className="grid gap-3 md:grid-cols-2">
        <Switch
          on={cfg.enabled}
          set={set('enabled')}
          label="فعال‌سازی ورود با تلگرام"
          hint="کلید اصلی؛ با خاموش بودن، هیچ دکمهٔ تلگرامی در فروشگاه نمایش داده نمی‌شود و درخواست‌های باز بسته می‌شوند."
        />
        <Switch
          on={cfg.store_login}
          set={set('store_login')}
          label="ورود مشتریان (فروشگاه)"
          hint="دکمه‌های تلگرام در پنجرهٔ ورود فروشگاه."
        />
        <Switch
          on={cfg.bot_login}
          set={set('bot_login')}
          label="روش ۱: تأیید در ربات"
          hint="بدون داده‌ی اضافه؛ با تطبیق عدد و نمایش دستگاه/IP."
        />
        <Switch
          on={cfg.oidc_login}
          set={set('oidc_login')}
          label="روش ۲: ورود مستقیم (OpenID Connect)"
          hint="نیازمند Client ID و Client Secret از BotFather."
        />
      </div>

      {cfg.bot_login && (
        <div className="space-y-3 rounded-xl border border-[var(--ln)] p-4">
          <div className="text-sm font-bold">تنظیمات روش «تأیید در ربات»</div>
          <div className="grid gap-3 md:grid-cols-2">
            <Switch
              on={cfg.number_match}
              set={set('number_match')}
              label="تطبیق عدد (توصیه‌شده)"
              hint="مشتری باید همان عدد نمایش‌داده‌شده در سایت را در ربات انتخاب کند؛ ضدفیشینگ."
            />
            <Field
              label="مدت اعتبار درخواست (ثانیه)"
              error={ttlError}
              hint={`بین ${cfg.ttl_min} و ${cfg.ttl_max}. پیش‌فرض ۱۸۰.`}
            >
              <input
                dir="ltr"
                type="number"
                min={cfg.ttl_min}
                max={cfg.ttl_max}
                className="inp font-mono text-xs"
                value={cfg.ttl_seconds}
                onChange={(e) => set('ttl_seconds')(e.target.value)}
              />
            </Field>
          </div>
          <MainBotBox
            key={saved.main_bot_username || 'none'}
            saved={saved}
            base={api.base}
            toast={toast}
            reload={reloadBot}
          />
        </div>
      )}

      {cfg.oidc_login && (
        <div className="space-y-4 rounded-xl border border-[var(--ln)] p-4">
          <div className="text-sm font-bold">اطلاعات «ورود مستقیم» (از BotFather ← Bot Settings ← Web Login)</div>
          <Field label="Client ID (شناسهٔ عددی ربات)" error={idError} hint="فقط عدد؛ همان عدد قبل از «:» در توکن ربات.">
            <input
              dir="ltr"
              inputMode="numeric"
              spellCheck={false}
              autoComplete="off"
              className="inp font-mono text-xs"
              value={cfg.client_id}
              onChange={(e) => set('client_id')(e.target.value)}
              placeholder="123456789"
            />
            {cfg.suggested_client_id && cfg.suggested_client_id !== id && (
              <button
                type="button"
                className="btn btn-g mt-2 !px-2 !py-1 text-xs"
                onClick={() => set('client_id')(cfg.suggested_client_id)}
              >
                استفاده از شناسهٔ ربات اصلی ({cfg.suggested_client_id})
              </button>
            )}
          </Field>
          <Field
            label="Client Secret"
            hint={
              cfg.client_secret_set && !clearSecret
                ? 'یک Secret ذخیره شده است و نمایش داده نمی‌شود. برای تغییر، مقدار جدید را وارد کنید.'
                : 'از همان صفحهٔ BotFather کپی کنید. رمزنگاری‌شده ذخیره می‌شود.'
            }
          >
            <PasswordInput
              spellCheck={false}
              autoComplete="new-password"
              className="inp font-mono text-xs"
              value={secret}
              onChange={(e: Json) => {
                setSecret(e.target.value);
                setClearSecret(false);
                setResult(null);
              }}
              placeholder={cfg.client_secret_set && !clearSecret ? '••••••••••••• (ذخیره‌شده)' : 'Client Secret'}
            />
            {cfg.client_secret_set && (
              <label className="mt-2 flex cursor-pointer items-center gap-2 text-xs font-normal">
                <input
                  type="checkbox"
                  checked={clearSecret}
                  onChange={(e) => {
                    setClearSecret(e.target.checked);
                    if (e.target.checked) setSecret('');
                  }}
                />
                حذف Secret ذخیره‌شده
              </label>
            )}
          </Field>
          <div className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="text-xs font-bold text-[var(--mu)]">
                Allowed URLs که باید در BotFather ثبت شوند (هر ردیف جدا)
              </div>
              <CopyAll lines={[...cfg.origins, ...cfg.redirect_uris]} />
            </div>
            <div className="grid gap-1.5 md:grid-cols-2">
              {[...cfg.origins, ...cfg.redirect_uris].map((u) => (
                <CopyBox key={u} text={u} />
              ))}
            </div>
            <p className="text-xs text-[var(--mu)]">
              هم آدرس سایت (origin) و هم آدرس بازگشت (<code dir="ltr">/callback</code>) را ثبت کنید. دامنهٔ هر نمایندهٔ
              فعال هم در فهرست آمده است.
            </p>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button
          disabled={busy === 'save' || !canSave || (!dirty && saved.source === 'panel')}
          className="btn"
          onClick={save}
        >
          {busy === 'save' ? 'در حال ذخیره...' : 'ذخیره'}
        </button>
        <button
          disabled={busy === 'test' || dirty}
          title={dirty ? 'ابتدا تغییرات را ذخیره کنید' : undefined}
          className="btn btn-g"
          onClick={test}
        >
          {busy === 'test' ? 'در حال تست...' : 'تست اتصال'}
        </button>
        {dirty && <span className="text-xs font-bold text-[var(--wn,#b7791f)]">تغییرات ذخیره‌نشده</span>}
        {!canSave && cfg.enabled && (
          <span className="text-xs text-[var(--bd)]">
            {ttlError ||
              idError ||
              (!(cfg.bot_login || cfg.oidc_login)
                ? 'حداقل یک روش را روشن کنید.'
                : 'برای ورود مستقیم، Client ID و Client Secret لازم است.')}
          </span>
        )}
      </div>
      {result && (
        <ul className="space-y-1.5 rounded-xl border border-[var(--ln)] p-3 text-xs leading-6">
          {result.checks.map((c: Json) => {
            const [m, cls] = MARK[c.status] || MARK.warn;
            return (
              <li key={c.key} className="flex gap-2">
                <b className={`w-4 shrink-0 text-center ${cls}`}>{m}</b>
                <span>{c.message}</span>
              </li>
            );
          })}
        </ul>
      )}
      <p className="text-xs text-[var(--mu)]">
        «تست اتصال» روی مقدار <b>ذخیره‌شده</b> کار می‌کند؛ ابتدا ذخیره کنید. درستیِ Allowed URLs فقط با یک ورود واقعی
        مشخص می‌شود.
      </p>

      <Guide cfg={cfg} />
    </section>
  );
}
