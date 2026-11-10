import { useEffect, useState } from 'react';
import {
  BarChart3,
  Gauge,
  Activity,
  Bot,
  CreditCard,
  Eye,
  EyeOff,
  Globe,
  Settings,
  Tags,
  Users,
  Webhook,
  KeyRound,
  BellRing,
  Megaphone,
  ShieldCheck,
  Gift,
  Percent,
  Award,
  ServerCog,
} from 'lucide-react';
import { Loading, StatusBadge, fd } from '../ui.jsx';
import { J, card, btn, ghost, inp } from './ResellerData.jsx';
import { errOf, DOMAIN_RE, TOKEN_RE, cleanDomain } from './ResellerSettings.jsx';

function DetailsForm({ onSubmit, busy }) {
  const [f, setF] = useState({ domain: '', bot_token: '' });
  const [show, setShow] = useState(false);
  const domain = cleanDomain(f.domain);
  const token = f.bot_token.trim();
  const bad = { domain: f.domain && !DOMAIN_RE.test(domain), token: f.bot_token && !TOKEN_RE.test(token) };
  return (
    <div className="mt-4 grid gap-4">
      <p className="rounded-xl bg-accent-soft p-3 text-sm leading-7">
        درخواست شما تأیید شد. برای ساخت فروشگاه، دامنه و توکن ربات تلگرام را بفرستید (می‌توانید همین کار را در ربات
        تلگرام با دستور /reseller هم انجام دهید).
      </p>
      <label className="text-xs font-bold">
        <span className="flex items-center gap-1.5">
          <Globe size={14} />
          دامنهٔ فروشگاه
        </span>
        <input
          dir="ltr"
          className={`${inp} latin mt-1.5 ${bad.domain ? '!border-danger' : ''}`}
          placeholder="shop.example.com"
          value={f.domain}
          onChange={(e) => setF({ ...f, domain: e.target.value })}
          aria-invalid={!!bad.domain}
        />
      </label>
      <label className="text-xs font-bold">
        <span className="flex items-center gap-1.5">
          <Bot size={14} />
          توکن ربات تلگرام
        </span>
        <span className="relative mt-1.5 block">
          <input
            dir="ltr"
            type={show ? 'text' : 'password'}
            autoComplete="off"
            spellCheck={false}
            className={`${inp} latin !pl-11 ${bad.token ? '!border-danger' : ''}`}
            placeholder="123456789:AA…"
            value={f.bot_token}
            onChange={(e) => setF({ ...f, bot_token: e.target.value })}
            aria-invalid={!!bad.token}
          />
          <button
            type="button"
            onClick={() => setShow((x) => !x)}
            aria-label={show ? 'پنهان‌کردن توکن' : 'نمایش توکن'}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-muted"
          >
            {show ? <EyeOff size={17} /> : <Eye size={17} />}
          </button>
        </span>
      </label>
      <button
        className={btn}
        disabled={busy || !DOMAIN_RE.test(domain) || !TOKEN_RE.test(token)}
        onClick={() => onSubmit(domain, token)}
      >
        {busy ? 'در حال ساخت…' : 'ساخت فروشگاه'}
      </button>
    </div>
  );
}

function ApplicationCard({ a, onCancel, onDetails, busy }) {
  const pending = a.status === 'pending';
  const awaiting = a.status === 'awaiting_details';
  return (
    <div className={`${card} ${pending || awaiting ? 'border-accent/40' : ''}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs text-muted">{fd(a.created_at)}</div>
          <h4 className="mt-1 text-lg font-extrabold">{a.store_name}</h4>
        </div>
        <StatusBadge status={a.status} />
      </div>
      <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
        <div className="flex items-center gap-2">
          <Globe size={16} className="text-muted" />
          <dd dir="ltr" className="latin font-bold">
            {a.domain || '—'}
          </dd>
        </div>
        <div className="flex items-center gap-2">
          <Bot size={16} className="text-muted" />
          <dd dir="ltr" className="latin font-bold">
            {a.bot_username ? `@${a.bot_username}` : '—'}
          </dd>
        </div>
      </dl>
      {pending && (
        <p className="mt-4 rounded-xl bg-accent-soft p-3 text-sm leading-7">
          درخواست شما در صف بررسی مدیریت است. پس از تأیید، فروشگاه نمایندگی ساخته می‌شود و همین‌جا «پنل نماینده» برایتان
          باز می‌شود.
        </p>
      )}
      {(pending || awaiting || a.status === 'approved') && a.next_steps?.length > 0 && (
        <div className="mt-4 rounded-xl border border-line p-4">
          <h5 className="text-sm font-extrabold">کارهایی که باید انجام دهید</h5>
          <ol className="mt-3 space-y-2.5 text-sm leading-7">
            {a.next_steps.map((st, i) => (
              <li key={i} className={`flex gap-2 ${st.done ? 'text-muted line-through' : ''}`}>
                <span className="font-bold">{i + 1}.</span>
                <span>
                  <b>{st.title}</b> — {st.detail}
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}
      {awaiting && <DetailsForm onSubmit={(domain, token) => onDetails(a, domain, token)} busy={busy} />}
      {a.status === 'rejected' && (
        <p className="mt-4 rounded-xl bg-danger-soft p-3 text-sm leading-7">
          <b>دلیل رد:</b> {a.review_reason || '—'}
        </p>
      )}
      {(pending || awaiting) && (
        <button className={`${ghost} mt-4`} disabled={busy} onClick={() => onCancel(a)}>
          لغو درخواست
        </button>
      )}
    </div>
  );
}

export function Apply({ coreFetch, notify, stores }) {
  const choices = (stores || []).filter((s) => s.status !== 'suspended');
  const [f, setF] = useState({
    store_name: '',
    message: '',
    domain: '',
    bot_token: '',
    target_store_id: choices.find((s) => s.kind === 'main')?.id || '',
  });
  const [apps, setApps] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [show, setShow] = useState(false);
  const loadApps = () =>
    coreFetch('/api/v1/reseller/applications')
      .then((r) => (r.ok ? r.json() : []))
      .then(setApps)
      .catch(() => setApps([]));
  useEffect(() => {
    loadApps();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- T-W08: reviewed, dependency list intentionally limited (adding the flagged value risks refetch loops); verify in a browser before changing
  }, []);
  const domain = cleanDomain(f.domain);
  const token = f.bot_token.trim();
  const bad = { domain: f.domain && !DOMAIN_RE.test(domain), token: f.bot_token && !TOKEN_RE.test(token) };
  const reasonOk = f.message.trim().length >= 20;
  const ready =
    f.store_name.trim().length >= 2 && f.target_store_id && DOMAIN_RE.test(domain) && TOKEN_RE.test(token) && reasonOk;
  const send = async () => {
    setBusy(true);
    setErr('');
    try {
      const r = await coreFetch('/api/v1/reseller/applications', {
        method: 'POST',
        headers: J,
        body: JSON.stringify({
          ...f,
          store_name: f.store_name.trim(),
          domain,
          bot_token: token,
          message: f.message.trim(),
        }),
      });
      if (r.ok) {
        setF({ ...f, store_name: '', message: '', domain: '', bot_token: '' });
        notify('درخواست ثبت شد؛ منتظر بررسی بمانید');
        await loadApps();
      } else setErr(await errOf(r, 'ثبت درخواست ناموفق بود'));
    } catch {
      setErr('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy(false);
    }
  };
  const cancel = async (a) => {
    if (!window.confirm('درخواست لغو شود؟ می‌توانید بعداً دوباره ثبت کنید.')) return;
    setBusy(true);
    const r = await coreFetch(`/api/v1/reseller/applications/${a.id}/cancel`, { method: 'POST' });
    setBusy(false);
    notify(r.ok ? 'درخواست لغو شد' : 'لغو درخواست ناموفق بود');
    r.ok && loadApps();
  };
  const details = async (a, domain, token) => {
    setBusy(true);
    setErr('');
    try {
      const r = await coreFetch(`/api/v1/reseller/applications/${a.id}/details`, {
        method: 'POST',
        headers: J,
        body: JSON.stringify({ domain, bot_token: token }),
      });
      if (r.ok) {
        notify('فروشگاه نمایندگی ساخته شد');
        window.location.reload();
      } else {
        const m = await errOf(r, 'ثبت اطلاعات ناموفق بود');
        setErr(m);
        notify(m);
      }
    } catch {
      setErr('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy(false);
    }
  };
  if (apps === null) return <Loading rows={2} />;
  const open = (a) => a.status === 'pending' || a.status === 'awaiting_details';
  const pending = apps.find(open);
  const history = apps.filter((a) => !open(a)).slice(0, 3);
  return (
    <div className="mx-auto max-w-2xl space-y-5">
      {pending ? (
        <>
          <ApplicationCard a={pending} onCancel={cancel} onDetails={details} busy={busy} />
          {err && (
            <p role="alert" className="rounded-xl bg-danger-soft p-3 text-sm text-danger">
              {err}
            </p>
          )}
        </>
      ) : (
        <div className={card}>
          <h3 className="text-xl font-extrabold">درخواست نمایندگی</h3>
          <p className="mt-2 text-sm leading-7 text-muted">
            فروشگاه و ربات تلگرام اختصاصی خودت را داشته باش. فقط برای فروشگاهی درخواست بده که عضو فعال آن هستی؛ برای چند
            فروشگاه می‌توانی جداگانه درخواست بدهی.
          </p>
          <div className="mt-5 grid gap-4">
            {choices.length > 1 && (
              <label className="text-xs font-bold">
                فروشگاه مقصد
                <select
                  className={`${inp} mt-1.5`}
                  value={f.target_store_id}
                  onChange={(e) => setF({ ...f, target_store_id: e.target.value })}
                >
                  {choices.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name} ({s.kind === 'main' ? 'اصلی' : 'فروشگاه'})
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label className="text-xs font-bold">
              نام فروشگاه نمایندگی
              <input
                className={`${inp} mt-1.5`}
                maxLength={200}
                value={f.store_name}
                onChange={(e) => setF({ ...f, store_name: e.target.value })}
              />
            </label>
            <label className="text-xs font-bold">
              <span className="flex items-center gap-1.5">
                <Globe size={14} />
                دامنهٔ فروشگاه
              </span>
              <input
                dir="ltr"
                className={`${inp} latin mt-1.5 ${bad.domain ? '!border-danger' : ''}`}
                placeholder="shop.example.com"
                value={f.domain}
                onChange={(e) => setF({ ...f, domain: e.target.value })}
                aria-invalid={!!bad.domain}
              />
              <span className={`mt-1 block text-[11px] font-normal ${bad.domain ? 'text-danger' : 'text-muted'}`}>
                {bad.domain ? 'نام دامنه معتبر نیست.' : 'بدون http و مسیر؛ هر دامنه فقط برای یک فروشگاه ثبت می‌شود.'}
              </span>
            </label>
            <label className="text-xs font-bold">
              <span className="flex items-center gap-1.5">
                <Bot size={14} />
                توکن ربات تلگرام
              </span>
              <span className="relative mt-1.5 block">
                <input
                  dir="ltr"
                  type={show ? 'text' : 'password'}
                  autoComplete="off"
                  spellCheck={false}
                  className={`${inp} latin !pl-11 ${bad.token ? '!border-danger' : ''}`}
                  placeholder="123456789:AA…"
                  value={f.bot_token}
                  onChange={(e) => setF({ ...f, bot_token: e.target.value })}
                  aria-invalid={!!bad.token}
                />
                <button
                  type="button"
                  onClick={() => setShow((x) => !x)}
                  aria-label={show ? 'پنهان‌کردن توکن' : 'نمایش توکن'}
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-muted"
                >
                  {show ? <EyeOff size={17} /> : <Eye size={17} />}
                </button>
              </span>
              <span
                className={`mt-1 block text-[11px] font-normal leading-6 ${bad.token ? 'text-danger' : 'text-muted'}`}
              >
                {bad.token
                  ? 'قالب توکن درست نیست (مثل 123456789:AA…).'
                  : 'از @BotFather با دستور /newbot بساز. توکن رمزنگاری ذخیره می‌شود و بعد از ثبت دیگر نمایش داده نمی‌شود.'}
              </span>
            </label>
            <label className="text-xs font-bold">
              توضیحات و دلیل درخواست نمایندگی (الزامی)
              <textarea
                rows={4}
                maxLength={2000}
                required
                className={`${inp} mt-1.5`}
                value={f.message}
                onChange={(e) => setF({ ...f, message: e.target.value })}
              />
              <span
                className={`mt-1 block text-[11px] font-normal leading-6 ${f.message && !reasonOk ? 'text-danger' : 'text-muted'}`}
              >
                چرا می‌خواهید نماینده شوید؟ سابقهٔ فروش، تعداد مشتری و برنامهٔ خود را بنویسید (حداقل ۲۰ نویسه).
              </span>
            </label>
          </div>
          {err && (
            <p role="alert" className="mt-4 rounded-xl bg-danger-soft p-3 text-sm text-danger">
              {err}
            </p>
          )}
          <button disabled={!ready || busy} onClick={send} className={`${btn} mt-5`}>
            {busy ? 'در حال ثبت…' : 'ارسال درخواست'}
          </button>
        </div>
      )}
      {history.map((a) => (
        <ApplicationCard key={a.id} a={a} onCancel={cancel} onDetails={details} busy={busy} />
      ))}
    </div>
  );
}

export const tabs = [
  ['overview', 'نمای کلی', BarChart3],
  ['pricing', 'قیمت‌گذاری', Tags],
  ['coupons', 'کدهای تخفیف', Percent],
  ['referral', 'برنامهٔ معرفی', Gift],
  ['loyalty', 'باشگاه مشتریان', Award],
  ['customers', 'مشتریان', Users],
  ['accounts', 'اکانت‌های مشتریان', Gauge],
  ['usage', 'گزارش مصرف', Activity],
  ['broadcast', 'پیام همگانی', Megaphone],
  ['events', 'مرکز رویداد', BellRing],
  ['payments', 'پرداخت‌ها', CreditCard],
  ['banksms', 'تأیید خودکار بانک', ShieldCheck],
  ['keys', 'کلیدهای API', KeyRound],
  ['hooks', 'وبهوک‌ها', Webhook],
  ['paneladmin', 'ادمین پنل', ServerCog],
  ['settings', 'تنظیمات فروشگاه', Settings],
];
