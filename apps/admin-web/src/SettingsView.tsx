import { Segmented } from './kit.tsx';
import type { ReactNode } from 'react';
import { lazy, Suspense, useEffect, useState } from 'react';
import { authFetch } from './api.ts';
import { PasswordInput, confirmDialog } from './ui.tsx';
import type { Json, Rec, Toast } from './types.ts';
import { box, inp, btn, ghost, useList, Table } from './adminExtraKit.tsx';

const GoogleLoginSettings = lazy(() => import('./GoogleLoginSettings.tsx'));
const TelegramLoginSettings = lazy(() => import('./TelegramLoginSettings.tsx'));

function SettingRow({ k, v, save }: { k?: Json; v?: Json; save?: Json }) {
  const [t, setT] = useState(JSON.stringify(v));
  useEffect(() => setT(JSON.stringify(v)), [v]);
  const dirty = t !== JSON.stringify(v);
  return (
    <div className="flex items-center gap-3 border-t border-[var(--ln)] px-5 py-3">
      <code dir="ltr" className="w-60 shrink-0 text-xs font-bold text-[var(--tx)]">
        {k}
      </code>
      <input dir="ltr" className={inp} value={t} onChange={(e) => setT(e.target.value)} />
      <button disabled={!dirty} className={btn} onClick={() => save(k, t)}>
        ذخیره
      </button>
    </div>
  );
}

const Field = ({ label, children }: { label?: Json; children?: ReactNode }) => (
  <label className="block text-xs font-bold text-[var(--mu)]">
    {label}
    <div className="mt-1">{children}</div>
  </label>
);
const Toggle = ({ on, set, label }: { on?: Json; set?: Json; label?: Json }) => (
  <label className="flex cursor-pointer items-center gap-2 text-sm font-bold">
    <input type="checkbox" checked={on} onChange={(e) => set(e.target.checked)} />
    {label}
  </label>
);

function Integrations({ api, toast }: { api?: Json; toast: Toast }) {
  const call = (p: Json, o = {}) => authFetch(api.base, p, o);
  const [aa, setAa] = useState<Json>(null);
  const [ipText, setIpText] = useState('');
  const [em, setEm] = useState<Json>(null);
  const [s3, setS3] = useState<Json>(null);
  const [local, setLocal] = useState<Json>(null);
  const [pw, setPw] = useState('');
  const [sk, setSk] = useState('');
  const [to, setTo] = useState('');
  const [busy, setBusy] = useState('');
  const load = () =>
    call('/api/v1/admin/integrations')
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => {
        setAa(d.admin_access);
        setIpText((d.admin_access?.ips || []).join('\n'));
        setEm(d.email);
        setS3(d.backup.s3);
        setLocal(d.backup.local);
        setPw('');
        setSk('');
      })
      .catch(() => toast('دریافت تنظیمات ناموفق بود'));
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- T-W08: reviewed, dependency list intentionally limited (adding the flagged value risks refetch loops); verify in a browser before changing
  }, []);
  if (!em || !s3 || !aa) return null;
  const send = async (path: string, body: Json, okMsg: Json, tag: Json) => {
    setBusy(tag);
    const r = await call(path, { method: path.endsWith('/test') ? 'POST' : 'PUT', body: JSON.stringify(body) });
    setBusy('');
    const d = await r.json().catch(() => ({}));
    if (!r.ok) return toast(d?.error?.message || d?.detail?.message || 'ذخیره ناموفق بود');
    if (path.endsWith('/test')) return toast(d.ok ? okMsg : `ناموفق: ${d.error || ''}`);
    toast(okMsg);
    load();
  };
  const sm = (k: Json) => (v: Json) => setEm({ ...em, [k]: v });
  const s3s = (k: Json) => (v: Json) => setS3({ ...s3, [k]: v });
  return (
    <section className={`${box} space-y-6 p-5`}>
      <h3 className="font-extrabold">
        یکپارچه‌سازی‌ها <span className="text-xs font-normal text-[var(--mu)]">(اختیاری؛ برای نصب لازم نیستند)</span>
      </h3>
      <div className="space-y-3 rounded-xl border border-[var(--ln)] p-4">
        <div className="flex items-center justify-between">
          <b>دسترسی ادمین (محدودیت IP)</b>
          <Toggle
            on={aa.enabled}
            set={(v: Json) => setAa({ ...aa, enabled: v })}
            label={aa.enabled ? 'فعال' : 'غیرفعال'}
          />
        </div>
        <p className="text-xs text-[var(--mu)]">
          به‌طور پیش‌فرض خاموش است. در حالت فعال، API ادمین فقط از IPها/CIDRهای زیر پاسخ می‌دهد (هر خط یک مورد). IP فعلی
          شما: <code dir="ltr">{aa.your_ip}</code>. اگر قفل شدید، روی سرور:{' '}
          <code dir="ltr">python -m melorin.cli disable-admin-ip-allowlist</code>
        </p>
        <textarea
          dir="ltr"
          rows={3}
          className={inp}
          value={ipText}
          onChange={(e) => setIpText(e.target.value)}
          placeholder={'203.0.113.10/32\n198.51.100.0/24'}
        />
        <button
          disabled={busy === 'aa'}
          className={btn}
          onClick={() =>
            send(
              '/api/v1/admin/integrations/admin-access',
              { enabled: aa.enabled, ips: ipText.split(/[\s,]+/).filter(Boolean) },
              'تنظیمات دسترسی ادمین ذخیره شد',
              'aa',
            )
          }
        >
          ذخیره
        </button>
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-3 rounded-xl border border-[var(--ln)] p-4">
          <div className="flex items-center justify-between">
            <b>ایمیل (SMTP)</b>
            <Toggle on={em.enabled} set={sm('enabled')} label={em.enabled ? 'فعال' : 'غیرفعال'} />
          </div>
          <p className="text-xs text-[var(--mu)]">
            وقتی غیرفعال است، ورود با کد ایمیلی در دسترس نیست؛ بقیه‌ی روش‌های ورود و سیستم عادی کار می‌کنند.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="میزبان SMTP">
              <input
                dir="ltr"
                className={inp}
                value={em.host}
                onChange={(e) => sm('host')(e.target.value)}
                placeholder="smtp.example.com"
              />
            </Field>
            <Field label="پورت">
              <input
                dir="ltr"
                type="number"
                className={inp}
                value={em.port}
                onChange={(e) => sm('port')(+e.target.value)}
              />
            </Field>
            <Field label="نام کاربری">
              <input dir="ltr" className={inp} value={em.username} onChange={(e) => sm('username')(e.target.value)} />
            </Field>
            <Field label={`رمز عبور${em.password_set ? ' (ذخیره شده؛ برای تغییر بنویسید)' : ''}`}>
              <PasswordInput
                autoComplete="new-password"
                className={inp}
                value={pw}
                onChange={(e: Json) => setPw(e.target.value)}
              />
            </Field>
            <Field label="آدرس فرستنده">
              <input
                dir="ltr"
                className={inp}
                value={em.from_addr}
                onChange={(e) => sm('from_addr')(e.target.value)}
                placeholder="no-reply@example.com"
              />
            </Field>
            <Field label="امنیت اتصال">
              <select className={inp} value={em.security} onChange={(e) => sm('security')(e.target.value)}>
                <option value="starttls">STARTTLS (۵۸۷)</option>
                <option value="ssl">SSL/TLS (۴۶۵)</option>
                <option value="none">بدون رمزنگاری</option>
              </select>
            </Field>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <button
              disabled={busy === 'em'}
              className={btn}
              onClick={() =>
                send(
                  '/api/v1/admin/integrations/email',
                  {
                    enabled: em.enabled,
                    host: em.host,
                    port: em.port,
                    username: em.username,
                    password: pw === '' ? null : pw,
                    from_addr: em.from_addr,
                    security: em.security,
                  },
                  'تنظیمات ایمیل ذخیره شد',
                  'em',
                )
              }
            >
              ذخیره
            </button>
            <input
              dir="ltr"
              className={`${inp} max-w-[14rem]`}
              value={to}
              onChange={(e) => setTo(e.target.value)}
              placeholder="ایمیل برای تست"
            />
            <button
              disabled={!to || busy === 'emt'}
              className={ghost}
              onClick={() => send('/api/v1/admin/integrations/email/test', { to }, 'ایمیل تست ارسال شد', 'emt')}
            >
              ارسال تست
            </button>
          </div>
        </div>
        <div className="space-y-3 rounded-xl border border-[var(--ln)] p-4">
          <div className="flex items-center justify-between">
            <b>بکاپ</b>
          </div>
          <p className="text-xs text-[var(--mu)]">
            بکاپ محلی همیشه فعال است (رمزگذاری‌شده، روزانه ۰۲:۰۰ UTC، نگهداری {local?.retention_days} روز در{' '}
            <code dir="ltr">{local?.dir}</code>). کپی خارج از سرور روی S3 اختیاری است.
          </p>
          <Toggle on={s3.enabled} set={s3s('enabled')} label={s3.enabled ? 'کپی روی S3 فعال' : 'کپی روی S3 غیرفعال'} />
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Endpoint (برای S3 سازگار)">
              <input
                dir="ltr"
                className={inp}
                value={s3.endpoint}
                onChange={(e) => s3s('endpoint')(e.target.value)}
                placeholder="https://s3.example.com"
              />
            </Field>
            <Field label="Region">
              <input
                dir="ltr"
                className={inp}
                value={s3.region}
                onChange={(e) => s3s('region')(e.target.value)}
                placeholder="us-east-1"
              />
            </Field>
            <Field label="Bucket">
              <input dir="ltr" className={inp} value={s3.bucket} onChange={(e) => s3s('bucket')(e.target.value)} />
            </Field>
            <Field label="Prefix">
              <input dir="ltr" className={inp} value={s3.prefix} onChange={(e) => s3s('prefix')(e.target.value)} />
            </Field>
            <Field label="Access Key">
              <input
                dir="ltr"
                className={inp}
                value={s3.access_key}
                onChange={(e) => s3s('access_key')(e.target.value)}
              />
            </Field>
            <Field label={`Secret Key${s3.secret_key_set ? ' (ذخیره شده؛ برای تغییر بنویسید)' : ''}`}>
              <PasswordInput
                autoComplete="new-password"
                className={inp}
                value={sk}
                onChange={(e: Json) => setSk(e.target.value)}
              />
            </Field>
          </div>
          <div className="flex gap-2">
            <button
              disabled={busy === 's3'}
              className={btn}
              onClick={() =>
                send(
                  '/api/v1/admin/integrations/backup-s3',
                  {
                    enabled: s3.enabled,
                    endpoint: s3.endpoint,
                    region: s3.region,
                    bucket: s3.bucket,
                    prefix: s3.prefix,
                    access_key: s3.access_key,
                    secret_key: sk === '' ? null : sk,
                  },
                  'تنظیمات S3 ذخیره شد',
                  's3',
                )
              }
            >
              ذخیره
            </button>
            <button
              disabled={busy === 's3t'}
              className={ghost}
              onClick={() => send('/api/v1/admin/integrations/backup-s3/test', {}, 'اتصال به S3 موفق بود', 's3t')}
            >
              تست اتصال
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}

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

const SETTINGS_TABS = ['integrations', 'login', 'advanced'];
const settingsTabFromHash = () => {
  const q = typeof window === 'undefined' ? '' : window.location.hash.split('?')[1] || '';
  const t = new URLSearchParams(q).get('tab') ?? '';
  return SETTINGS_TABS.includes(t) ? t : 'integrations';
};

export default function Settings({ api, toast }: { api?: Json; toast: Toast }) {
  // Sign-in methods (Google / Telegram) live here, owner-only (server area `system`); Receipt OCR in Payments, the password form in My account.
  const [tab, setTab] = useState(settingsTabFromHash);
  const pick = (v: string) => {
    setTab(v);
    window.history.replaceState(
      null,
      '',
      `${window.location.pathname}${window.location.search}#/settings${v === 'integrations' ? '' : `?tab=${v}`}`,
    );
  };
  const flags = useList(api, '/api/v1/admin/feature-flags', toast);
  const [obj, setObj] = useState<Rec>({});
  const [tick, setTick] = useState(0);
  useEffect(() => {
    flags
      .call('/api/v1/admin/settings')
      .then((r) => (r.ok ? r.json() : {}))
      .then(setObj);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- T-W08: reviewed, dependency list intentionally limited (adding the flagged value risks refetch loops); verify in a browser before changing
  }, [tick]);
  const setFlag = async (f: Json) => {
    const r = await flags.call(`/api/v1/admin/feature-flags/${encodeURIComponent(f.key)}`, {
      method: 'PUT',
      body: JSON.stringify({ enabled: !f.enabled, scope_type: f.scope_type, scope_id: f.scope_id, note: f.note }),
    });
    r.ok ? flags.reload() : toast('تغییر ناموفق بود');
  };
  const save = async (key: Json, text: Json) => {
    let value;
    try {
      value = JSON.parse(text);
    } catch {
      return toast('مقدار باید JSON معتبر باشد');
    }
    if (!(await confirmDialog(`مقدار «${key}» تغییر کند؟`, { title: 'تغییر تنظیم سیستم', ok: 'ذخیره' }))) return;
    const r = await flags.call(`/api/v1/admin/settings/${key}`, { method: 'PUT', body: JSON.stringify({ value }) });
    if (r.ok) {
      toast('تنظیم ذخیره شد');
      setTick((x) => x + 1);
    } else toast('ذخیره ناموفق بود');
  };
  const rawSettings = Object.entries(obj).filter(([k]) => !['card.info', 'gateway.zarinpal'].includes(k));
  return (
    <div className="space-y-5">
      <Segmented
        label="بخش تنظیمات"
        value={tab}
        onChange={pick}
        options={[
          ['integrations', 'پشتیبان‌گیری و ایمیل'],
          ['login', 'روش‌های ورود'],
          ['advanced', 'پیشرفته'],
        ]}
      />
      {tab === 'integrations' && <Integrations api={api} toast={toast} />}
      {tab === 'login' && (
        <Suspense fallback={<div className="skel h-44" />}>
          <div className="space-y-5">
            <GoogleLoginSettings api={api} toast={toast} />
            <TelegramLoginSettings api={api} toast={toast} />
          </div>
        </Suspense>
      )}
      {tab === 'advanced' && (
        <>
          <Table
            title="Feature Flags"
            cols={['کلید', 'محدوده', 'فعال', '']}
            rows={flags.rows.map((f) => [
              f.key,
              `${f.scope_type}:${f.scope_id}`,
              f.enabled ? 'بله' : 'خیر',
              <button key="flag" className={ghost} onClick={() => setFlag(f)}>
                {f.enabled ? 'خاموش' : 'روشن'}
              </button>,
            ])}
          />
          <section className={`${box} overflow-hidden`}>
            <h3 className="px-5 py-4 font-extrabold">
              تنظیمات پیشرفته سیستم <span className="text-xs font-normal text-[var(--mu)]">(مقدار به‌صورت JSON)</span>
            </h3>
            {rawSettings.map(([k, v]) => (
              <SettingRow key={k} k={k} v={v} save={save} />
            ))}
          </section>
        </>
      )}
    </div>
  );
}
