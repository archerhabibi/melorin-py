// تأیید خودکار کارت‌به‌کارت با پیامک بانک (reseller): the owner's phone forwards every bank SMS to Core; Core parses it,
// matches it with a customer receipt (same amount + the time printed on the receipt) and credits the wallet. This tab
// only edits the settings, shows the forwarded SMS and lets a human settle what the matcher refused to guess.
import { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, Copy, KeyRound, RefreshCw, ShieldCheck, Smartphone } from 'lucide-react';
import { Loading, fa, fd } from './ui.jsx';

const J = { 'Content-Type': 'application/json' };
const chip = 'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-bold';
const STATUS = {
  matched: ['شارژ شد', 'bg-mint/15 text-mint'],
  unmatched: ['در انتظار رسید', 'bg-surface2 text-muted'],
  ambiguous: ['نیاز به بررسی', 'bg-danger-soft text-danger'],
  ignored: ['نادیده', 'bg-surface2 text-muted'],
  unparsed: ['نامفهوم', 'bg-danger-soft text-danger'],
};
const toInt = (s) => {
  const t = String(s ?? '')
    .replace(/[۰-۹]/g, (d) => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d))
    .replace(/\D/g, '');
  return t === '' ? null : Number(t);
};

async function message(r, fallback) {
  const d = await r.json().catch(() => ({}));
  return d?.error?.message || (typeof d?.detail === 'string' ? d.detail : '') || fallback;
}

export default function ResellerBankSms({ coreFetch, base, notify }) {
  const url = `${base}/bank-sms`;
  const storeId = (base.match(/\/stores\/([^/]+)/) || [])[1] || '';
  const webhook = `${window.location.origin}/api/v1/payments/bank-sms/${storeId}`;
  const [data, setData] = useState(null);
  const [form, setForm] = useState(null);
  const [token, setToken] = useState(null);
  const [filter, setFilter] = useState('');
  const [open, setOpen] = useState([]);
  const [busy, setBusy] = useState('');

  const apply = (d) => {
    setData(d);
    const s = d.source;
    setForm({
      auto_verify: !!s.auto_verify,
      is_enabled: s.configured ? !!s.is_enabled : true,
      senders: (s.senders || []).join('\n'),
      window_minutes: String(s.settings.window_minutes),
      time_tolerance_minutes: String(s.settings.time_tolerance_minutes),
      require_claimed_time: !!s.settings.require_claimed_time,
      max_auto_amount_rial: s.settings.max_auto_amount_rial ? String(s.settings.max_auto_amount_rial) : '',
      account_number: s.settings.account_number || '',
    });
  };
  const load = useCallback(async () => {
    const r = await coreFetch(`${url}${filter ? `?status=${filter}` : ''}`);
    if (r.ok) apply(await r.json());
    else notify(await message(r, 'دریافت اطلاعات پیامک ناموفق بود'));
    const p = await coreFetch(`${base}/payments`);
    if (p.ok) setOpen((await p.json()).filter((x) => x.status === 'awaiting_review' && x.has_receipt));
  }, [coreFetch, url, base, filter, notify]);
  useEffect(() => {
    load().catch(() => {});
  }, [load]);

  const run = async (key, fn) => {
    setBusy(key);
    try {
      await fn();
    } finally {
      setBusy('');
    }
  };
  const save = () =>
    run('save', async () => {
      const body = {
        is_enabled: form.is_enabled,
        auto_verify: form.auto_verify,
        senders: form.senders
          .split(/[\n,]/)
          .map((x) => x.trim())
          .filter(Boolean),
        settings: {
          window_minutes: toInt(form.window_minutes),
          time_tolerance_minutes: toInt(form.time_tolerance_minutes),
          require_claimed_time: form.require_claimed_time,
          max_auto_amount_rial: toInt(form.max_auto_amount_rial),
          account_number: String(form.account_number).replace(/\s/g, '') || null,
        },
      };
      const r = await coreFetch(`${url}/source`, { method: 'PUT', headers: J, body: JSON.stringify(body) });
      if (!r.ok) return notify(await message(r, 'ذخیره ناموفق بود'));
      const d = await r.json();
      if (d.token) setToken(d.token);
      notify('تنظیمات ذخیره شد');
      load();
    });
  const rotate = () =>
    run('rotate', async () => {
      if (!window.confirm('توکن قبلی از کار می‌افتد و باید در برنامه‌ی ارسال پیامک تعویض شود. ادامه می‌دهید؟')) return;
      const r = await coreFetch(`${url}/token`, { method: 'POST' });
      if (!r.ok) return notify(await message(r, 'تعویض توکن ناموفق بود'));
      setToken((await r.json()).token);
      load();
    });
  const reconcile = () =>
    run('reconcile', async () => {
      const r = await coreFetch(`${url}/reconcile`, { method: 'POST' });
      if (!r.ok) return notify(await message(r, 'بررسی دوباره ناموفق بود'));
      const d = await r.json();
      notify(d.matched ? `${fa(d.matched)} پرداخت تطبیق و شارژ شد` : 'مورد جدیدی برای تطبیق نبود');
      load();
    });
  const ignore = (m, ignored) =>
    run(m.id, async () => {
      const r = await coreFetch(`${url}/${m.id}/ignore`, {
        method: 'POST',
        headers: J,
        body: JSON.stringify({ ignored }),
      });
      notify(r.ok ? 'ثبت شد' : await message(r, 'ناموفق بود'));
      r.ok && load();
    });
  const link = (m, paymentId) =>
    run(m.id, async () => {
      if (!paymentId) return;
      if (!window.confirm(`این پیامک (${fa(m.amount_rial)} ریال) به پرداخت انتخابی وصل و کیف پول مشتری شارژ شود؟`))
        return;
      const r = await coreFetch(`${url}/${m.id}/link`, {
        method: 'POST',
        headers: J,
        body: JSON.stringify({ payment_id: paymentId }),
      });
      notify(r.ok ? 'پرداخت تأیید و کیف پول شارژ شد' : await message(r, 'اتصال ناموفق بود'));
      r.ok && load();
    });

  if (!data || !form) return <Loading rows={2} />;
  const s = data.source;
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  const num = (k, label, hint) => (
    <label className="text-xs font-bold">
      {label}
      <input dir="ltr" inputMode="numeric" className="input mt-1 !py-2.5" value={form[k]} onChange={set(k)} />
      <span className="mt-1 block font-normal text-muted">{hint}</span>
    </label>
  );
  return (
    <div className="space-y-4">
      {token && (
        <div className="rounded-2xl border border-danger/30 bg-danger-soft p-4 text-sm" role="alert">
          <b>توکن وبهوک پیامک</b> — فقط همین یک‌بار نمایش داده می‌شود:
          <code dir="ltr" className="latin mt-2 block break-all rounded-xl bg-surface p-3 text-xs">
            {token}
          </code>
          <div className="mt-2 flex gap-2">
            <button className="btn-ghost" onClick={() => navigator.clipboard?.writeText(token)}>
              <Copy size={14} /> کپی
            </button>
            <button className="btn-ghost" onClick={() => setToken(null)}>
              بستن
            </button>
          </div>
        </div>
      )}
      <div className="card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h4 className="flex items-center gap-2 font-extrabold">
            <ShieldCheck size={18} /> تأیید خودکار کارت‌به‌کارت با پیامک بانک
          </h4>
          <span
            className={`${chip} ${s.configured && s.is_enabled && s.auto_verify ? 'bg-mint/15 text-mint' : 'bg-surface2 text-muted'}`}
          >
            {s.configured && s.is_enabled && s.auto_verify ? 'فعال' : 'غیرفعال'}
          </span>
        </div>
        <p className="mt-2 text-xs leading-6 text-muted">
          پیامک واریز بانک (قابل جعل‌نشدن) مبنای تأیید است، نه عکس رسید. فقط وقتی مبلغ، زمان رسید و پیامک بدون هیچ
          ابهامی یکی باشند، کیف پول به‌صورت خودکار شارژ می‌شود؛ در غیر این صورت پرداخت در صف بررسی دستی می‌ماند.
        </p>
        <label className="mt-3 flex items-center gap-2 text-sm font-bold">
          <input type="checkbox" checked={form.auto_verify} onChange={set('auto_verify')} />
          شارژ خودکار پس از تطبیق با پیامک
        </label>
        <label className="mt-2 flex items-center gap-2 text-sm">
          <input type="checkbox" checked={form.is_enabled} onChange={set('is_enabled')} />
          دریافت پیامک فعال باشد
        </label>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {num('window_minutes', 'بازه‌ی پذیرش (دقیقه)', 'پیامک تا این مدت بعد از درخواست شارژ پذیرفته می‌شود')}
          {num('time_tolerance_minutes', 'اختلاف مجاز زمان (دقیقه)', 'اختلاف زمان رسید و پیامک')}
          {num('max_auto_amount_rial', 'سقف شارژ خودکار (ریال)', 'خالی = بدون سقف؛ مبلغ بیشتر همیشه دستی بررسی می‌شود')}
          <label className="text-xs font-bold">
            شماره حساب (خط اول پیامک)
            <input
              dir="ltr"
              inputMode="numeric"
              className="input latin mt-1 !py-2.5"
              value={form.account_number}
              onChange={set('account_number')}
            />
            <span className="mt-1 block font-normal text-muted">
              اگر پر شود، پیامک حساب‌های دیگر نادیده گرفته می‌شود
            </span>
          </label>
          <label className="text-xs font-bold">
            فرستنده‌های مجاز (هر خط یکی)
            <textarea
              rows={2}
              dir="ltr"
              className="input latin mt-1 !py-2.5"
              value={form.senders}
              onChange={set('senders')}
              placeholder="خالی = هر فرستنده"
            />
          </label>
        </div>
        <label className="mt-3 flex items-center gap-2 text-sm">
          <input type="checkbox" checked={form.require_claimed_time} onChange={set('require_claimed_time')} />
          ثبت زمان رسید توسط مشتری الزامی باشد (توصیه‌شده)
        </label>
        <div className="mt-4 flex flex-wrap gap-2">
          <button className="btn-primary !py-2.5" disabled={busy === 'save'} onClick={save}>
            {s.configured ? 'ذخیره' : 'فعال‌سازی و ساخت توکن'}
          </button>
          {s.configured && (
            <>
              <button className="btn-ghost" disabled={busy === 'rotate'} onClick={rotate}>
                <KeyRound size={14} /> توکن جدید{s.token_hint ? ` (…${s.token_hint})` : ''}
              </button>
              <button className="btn-ghost" disabled={busy === 'reconcile'} onClick={reconcile}>
                <RefreshCw size={14} /> بررسی دوباره
              </button>
            </>
          )}
        </div>
      </div>
      {s.configured && (
        <div className="card text-sm leading-7">
          <h4 className="flex items-center gap-2 font-extrabold">
            <Smartphone size={18} /> اتصال گوشی (ارسال‌کننده‌ی پیامک)
          </h4>
          <p className="mt-2 text-xs text-muted">
            در برنامه‌ی SMS Forwarder گوشی‌ای که پیامک بانک را می‌گیرد، یک وبهوک POST با بدنه‌ی JSON بسازید:
          </p>
          <code dir="ltr" className="latin mt-2 block break-all rounded-xl bg-surface2 p-3 text-xs">
            POST {webhook}
            <br />
            X-Webhook-Token: &lt;token&gt;
            <br />
            {'{"text": "<متن پیامک>", "sender": "<فرستنده>"}'}
          </code>
          <p className="mt-2 text-xs text-muted">
            آخرین پیامک دریافتی: {s.last_received_at ? fd(s.last_received_at) : 'هنوز دریافت نشده'}
          </p>
        </div>
      )}
      {s.configured && (
        <div className="card overflow-x-auto">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h4 className="font-extrabold">پیامک‌های دریافتی</h4>
            <select
              className="input !w-auto !py-2"
              aria-label="فیلتر وضعیت"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            >
              <option value="">همه</option>
              {Object.entries(STATUS).map(([k, [l]]) => (
                <option key={k} value={k}>
                  {l}
                </option>
              ))}
            </select>
          </div>
          <table className="mt-3 w-full min-w-[640px] text-right text-sm">
            <thead className="text-xs text-muted [&_th]:pb-3 [&_th]:font-bold">
              <tr>
                <th>مبلغ (ریال)</th>
                <th>زمان پیامک</th>
                <th>شماره حساب</th>
                <th>وضعیت</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {data.messages.map((m) => {
                const [label, tone] = STATUS[m.status] || [m.status, 'bg-surface2 text-muted'];
                const same = open.filter(
                  (p) => m.amount_rial && (p.currency === 'IRR' ? p.amount : p.amount * 10) === m.amount_rial,
                );
                return (
                  <tr key={m.id} className="border-t border-line align-top">
                    <td className="py-3 font-bold" dir="ltr">
                      {m.direction === 'withdrawal' ? '−' : ''}
                      {m.amount_rial ? fa(m.amount_rial) : '—'}
                    </td>
                    <td>{m.occurred_at ? fd(m.occurred_at) : '—'}</td>
                    <td className="latin text-xs">{m.serial || '—'}</td>
                    <td>
                      <span className={`${chip} ${tone}`}>
                        {m.status === 'matched' && <CheckCircle2 size={12} />}
                        {label}
                      </span>
                      {m.balance_gap && (
                        <div className="mt-1 text-[11px] text-danger">مانده با پیامک قبلی نمی‌خواند</div>
                      )}
                    </td>
                    <td>
                      {(m.status === 'unmatched' || m.status === 'ambiguous') && (
                        <span className="flex flex-wrap gap-1.5">
                          {same.length > 0 && (
                            <select
                              className="input !w-auto !py-1.5 text-xs"
                              aria-label="اتصال به پرداخت"
                              disabled={busy === m.id}
                              value=""
                              onChange={(e) => link(m, e.target.value)}
                            >
                              <option value="">اتصال به پرداخت…</option>
                              {same.map((p) => (
                                <option key={p.id} value={p.id}>
                                  {fa(p.amount)} · {fd(p.created_at)}
                                </option>
                              ))}
                            </select>
                          )}
                          <button className="btn-ghost" disabled={busy === m.id} onClick={() => ignore(m, true)}>
                            نادیده
                          </button>
                        </span>
                      )}
                      {m.status === 'ignored' && m.direction === 'deposit' && (
                        <button className="btn-ghost" disabled={busy === m.id} onClick={() => ignore(m, false)}>
                          بازگردانی
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
              {!data.messages.length && (
                <tr>
                  <td colSpan={5} className="p-8 text-center text-muted">
                    پیامکی دریافت نشده است
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
