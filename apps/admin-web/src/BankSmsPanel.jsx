// تأیید خودکار کارت‌به‌کارت با پیامک بانک (main store): settings, one-time webhook token, the forwarded SMS inbox and the
// human fallback (pair / ignore). Core decides every match; this panel only edits settings and shows what Core stored.
import { useCallback, useEffect, useState } from 'react';
import { Copy, KeyRound, RefreshCw, ShieldCheck, Smartphone } from 'lucide-react';
import { Empty, Field, Section, Switch, errText, num } from './kit.jsx';
import { confirmDialog, dt } from './ui.jsx';

const STATUS = {
  matched: ['شارژ شد', 'b-ok'],
  unmatched: ['در انتظار رسید', 'b-mu'],
  ambiguous: ['نیاز به بررسی', 'b-wn'],
  ignored: ['نادیده', 'b-mu'],
  unparsed: ['نامفهوم', 'b-bd'],
};
const toInt = (s) => {
  const t = String(s ?? '')
    .replace(/[۰-۹]/g, (d) => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d))
    .replace(/\D/g, '');
  return t === '' ? null : Number(t);
};
const JSON_H = { 'Content-Type': 'application/json' };

export default function BankSmsPanel({ call, toast, payments }) {
  const [store, setStore] = useState(null);
  const [data, setData] = useState(null);
  const [form, setForm] = useState(null);
  const [token, setToken] = useState(null);
  const [filter, setFilter] = useState('');
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
    });
  };

  useEffect(() => {
    call('/api/v1/me/stores')
      .then((r) => (r.ok ? r.json() : []))
      .then((l) => setStore((l.find((x) => x.kind === 'main') || {}).id || false))
      .catch(() => setStore(false));
  }, [call]);

  const base = store ? `/api/v1/admin/stores/${store}/bank-sms` : null;
  const load = useCallback(async () => {
    if (!base) return;
    try {
      const r = await call(`${base}${filter ? `?status=${filter}` : ''}`);
      if (r.ok) apply(await r.json());
      else toast(await errText(r, 'دریافت پیامک‌های بانک ناموفق بود'));
    } catch {
      toast('ارتباط با سرور برقرار نشد');
    }
  }, [base, call, filter, toast]);
  useEffect(() => {
    load();
  }, [load]);

  const run = async (key, fn) => {
    setBusy(key);
    try {
      await fn();
    } catch {
      toast('ارتباط با سرور برقرار نشد');
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
        },
      };
      const r = await call(`${base}/source`, { method: 'PUT', headers: JSON_H, body: JSON.stringify(body) });
      if (!r.ok) return toast(await errText(r, 'ذخیره ناموفق بود'));
      const d = await r.json();
      if (d.token) setToken(d.token);
      toast('تنظیمات ذخیره شد');
      load();
    });
  const rotate = () =>
    run('rotate', async () => {
      if (
        !(await confirmDialog('توکن قبلی از کار می‌افتد و باید در برنامه‌ی ارسال پیامک تعویض شود.', {
          title: 'توکن جدید',
          ok: 'ساخت توکن جدید',
          danger: true,
        }))
      )
        return;
      const r = await call(`${base}/token`, { method: 'POST' });
      if (!r.ok) return toast(await errText(r, 'تعویض توکن ناموفق بود'));
      setToken((await r.json()).token);
      load();
    });
  const reconcile = () =>
    run('reconcile', async () => {
      const r = await call(`${base}/reconcile`, { method: 'POST' });
      if (!r.ok) return toast(await errText(r, 'بررسی دوباره ناموفق بود'));
      const d = await r.json();
      toast(d.matched ? `${num(d.matched)} پرداخت تطبیق و شارژ شد` : 'مورد جدیدی برای تطبیق نبود');
      load();
    });
  const ignore = (m, ignored) =>
    run(m.id, async () => {
      const r = await call(`${base}/${m.id}/ignore`, {
        method: 'POST',
        headers: JSON_H,
        body: JSON.stringify({ ignored }),
      });
      if (!r.ok) return toast(await errText(r, 'ناموفق بود'));
      load();
    });
  const link = (m, paymentId) =>
    run(m.id, async () => {
      if (!paymentId) return;
      if (
        !(await confirmDialog(
          `این پیامک (${num(m.amount_rial)} ریال) به پرداخت انتخابی وصل و کیف پول مشتری شارژ شود؟`,
          {
            title: 'اتصال پیامک به پرداخت',
            ok: 'اتصال و شارژ',
          },
        ))
      )
        return;
      const r = await call(`${base}/${m.id}/link`, {
        method: 'POST',
        headers: JSON_H,
        body: JSON.stringify({ payment_id: paymentId }),
      });
      toast(r.ok ? 'پرداخت تأیید و کیف پول شارژ شد' : await errText(r, 'اتصال ناموفق بود'));
      r.ok && load();
    });

  if (store === false || !form || !data) {
    return store === false ? null : <div className="card skel h-24" />;
  }
  const s = data.source;
  const live = s.configured && s.is_enabled && s.auto_verify;
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const waiting = (payments || []).filter(
    (p) => p.provider === 'manual_card' && p.status === 'awaiting_review' && p.has_receipt,
  );
  const webhook = `${window.location.origin}/api/v1/payments/bank-sms/${s.store_id}`;

  return (
    <Section
      title="تأیید خودکار کارت‌به‌کارت با پیامک بانک"
      hint="پیامک واریز بانک مبنای تأیید است، نه عکس رسید. فقط وقتی مبلغ، زمان رسید و پیامک بدون ابهام یکی باشند، کیف پول خودکار شارژ می‌شود."
    >
      {token && (
        <div className="rounded-xl border border-[var(--bd)] p-3 text-xs" role="alert">
          <b>توکن وبهوک پیامک</b> — فقط همین یک‌بار نمایش داده می‌شود:
          <code dir="ltr" className="mt-2 block break-all rounded-lg bg-[var(--bg2)] p-2 font-mono">
            {token}
          </code>
          <div className="mt-2 flex gap-2">
            <button className="btn btn-g !py-1.5" onClick={() => navigator.clipboard?.writeText(token)}>
              <Copy size={13} /> کپی
            </button>
            <button className="btn btn-g !py-1.5" onClick={() => setToken(null)}>
              بستن
            </button>
          </div>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-4">
        <span className={`badge ${live ? 'b-ok' : 'b-mu'}`}>
          <ShieldCheck size={13} /> {live ? 'شارژ خودکار فعال' : 'شارژ خودکار غیرفعال'}
        </span>
        <label className="flex items-center gap-2 text-xs font-bold">
          <Switch
            checked={form.auto_verify}
            onChange={(v) => setForm({ ...form, auto_verify: v })}
            label="شارژ خودکار"
          />
          شارژ خودکار پس از تطبیق
        </label>
        <label className="flex items-center gap-2 text-xs font-bold">
          <Switch
            checked={form.is_enabled}
            onChange={(v) => setForm({ ...form, is_enabled: v })}
            label="دریافت پیامک"
          />
          دریافت پیامک فعال
        </label>
        <label className="flex items-center gap-2 text-xs font-bold">
          <Switch
            checked={form.require_claimed_time}
            onChange={(v) => setForm({ ...form, require_claimed_time: v })}
            label="زمان رسید الزامی"
          />
          زمان رسید الزامی (توصیه‌شده)
        </label>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="بازه‌ی پذیرش (دقیقه)" hint="پیامک تا این مدت بعد از درخواست شارژ پذیرفته می‌شود">
          <input
            dir="ltr"
            inputMode="numeric"
            className="inp"
            value={form.window_minutes}
            onChange={set('window_minutes')}
          />
        </Field>
        <Field label="اختلاف مجاز زمان (دقیقه)" hint="اختلاف زمان رسید و پیامک">
          <input
            dir="ltr"
            inputMode="numeric"
            className="inp"
            value={form.time_tolerance_minutes}
            onChange={set('time_tolerance_minutes')}
          />
        </Field>
        <Field label="سقف شارژ خودکار (ریال)" hint="خالی = بدون سقف؛ مبلغ بیشتر همیشه دستی بررسی می‌شود">
          <input
            dir="ltr"
            inputMode="numeric"
            className="inp"
            value={form.max_auto_amount_rial}
            onChange={set('max_auto_amount_rial')}
          />
        </Field>
        <Field label="فرستنده‌های مجاز (هر خط یکی)" hint="خالی = هر فرستنده">
          <textarea dir="ltr" rows={2} className="inp font-mono" value={form.senders} onChange={set('senders')} />
        </Field>
      </div>
      <div className="flex flex-wrap gap-2">
        <button className="btn btn-p" disabled={busy === 'save'} onClick={save}>
          {s.configured ? 'ذخیره' : 'فعال‌سازی و ساخت توکن'}
        </button>
        {s.configured && (
          <>
            <button className="btn btn-g" disabled={busy === 'rotate'} onClick={rotate}>
              <KeyRound size={14} /> توکن جدید{s.token_hint ? ` (…${s.token_hint})` : ''}
            </button>
            <button className="btn btn-g" disabled={busy === 'reconcile'} onClick={reconcile}>
              <RefreshCw size={14} /> بررسی دوباره
            </button>
          </>
        )}
      </div>
      {s.configured && (
        <div className="rounded-xl bg-[var(--bg2)] p-3 text-xs leading-6">
          <b className="flex items-center gap-1.5">
            <Smartphone size={14} /> اتصال گوشی
          </b>
          در برنامه‌ی SMS Forwarder یک وبهوک POST (JSON) بسازید:
          <code dir="ltr" className="mt-1 block break-all font-mono">
            POST {webhook}
            <br />
            X-Webhook-Token: &lt;token&gt;
            <br />
            {'{"text": "<متن پیامک>", "sender": "<فرستنده>"}'}
          </code>
          <span className="text-[var(--mu)]">
            آخرین پیامک دریافتی: {s.last_received_at ? dt(s.last_received_at) : 'هنوز دریافت نشده'}
          </span>
        </div>
      )}
      {s.configured && (
        <>
          <div className="flex items-center justify-between gap-3">
            <h4 className="text-xs font-extrabold">پیامک‌های دریافتی</h4>
            <select
              aria-label="فیلتر وضعیت پیامک"
              className="inp !w-auto !py-1.5 !text-xs"
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
          {!data.messages.length ? (
            <Empty
              Icon={Smartphone}
              title="پیامکی دریافت نشده است"
              text="پس از اتصال گوشی، پیامک‌های واریز بانک اینجا نمایش داده می‌شوند."
            />
          ) : (
            <div className="overflow-auto">
              <table className="tbl2 min-w-[640px]">
                <thead>
                  <tr>
                    <th>مبلغ (ریال)</th>
                    <th>زمان پیامک</th>
                    <th>سریال</th>
                    <th>وضعیت</th>
                    <th className="!text-left">اقدام</th>
                  </tr>
                </thead>
                <tbody>
                  {data.messages.map((m) => {
                    const [label, tone] = STATUS[m.status] || [m.status, 'b-mu'];
                    const same = waiting.filter(
                      (p) => m.amount_rial && (p.currency === 'IRR' ? p.amount : p.amount * 10) === m.amount_rial,
                    );
                    return (
                      <tr key={m.id}>
                        <td dir="ltr" className="font-bold">
                          {m.direction === 'withdrawal' ? '−' : ''}
                          {m.amount_rial ? num(m.amount_rial) : '—'}
                        </td>
                        <td className="text-xs">{m.occurred_at ? dt(m.occurred_at) : '—'}</td>
                        <td dir="ltr" className="font-mono text-[11px]">
                          {m.serial || '—'}
                        </td>
                        <td>
                          <span className={`badge ${tone}`}>{label}</span>
                          {m.balance_gap && (
                            <div className="mt-1 text-[11px] text-[var(--bd)]">مانده با پیامک قبلی نمی‌خواند</div>
                          )}
                        </td>
                        <td>
                          {(m.status === 'unmatched' || m.status === 'ambiguous') && (
                            <span className="flex flex-wrap justify-end gap-1.5">
                              {same.length > 0 && (
                                <select
                                  className="inp !w-auto !py-1.5 !text-xs"
                                  aria-label="اتصال به پرداخت"
                                  disabled={busy === m.id}
                                  value=""
                                  onChange={(e) => link(m, e.target.value)}
                                >
                                  <option value="">اتصال به پرداخت…</option>
                                  {same.map((p) => (
                                    <option key={p.id} value={p.id}>
                                      {num(p.amount)} · {dt(p.created_at)}
                                    </option>
                                  ))}
                                </select>
                              )}
                              <button
                                className="btn btn-g !py-1.5"
                                disabled={busy === m.id}
                                onClick={() => ignore(m, true)}
                              >
                                نادیده
                              </button>
                            </span>
                          )}
                          {m.status === 'ignored' && m.direction === 'deposit' && (
                            <button
                              className="btn btn-g !py-1.5"
                              disabled={busy === m.id}
                              onClick={() => ignore(m, false)}
                            >
                              بازگردانی
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </Section>
  );
}
