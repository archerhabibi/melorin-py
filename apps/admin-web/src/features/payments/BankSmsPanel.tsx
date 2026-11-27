// تأیید خودکار کارت‌به‌کارت با پیامک بانک (main store): settings, one-time webhook token, the forwarded SMS inbox and the
// human fallback (pair / ignore). Core decides every match; this panel only edits settings and shows what Core stored.
// Every call goes through the typed client: paths, bodies and responses come from the OpenAPI snapshot.
import { useEffect, useMemo, useState, type ChangeEvent } from 'react';
import { Copy, KeyRound, RefreshCw, ShieldCheck, Smartphone } from 'lucide-react';
import { formFromSource, sourceBody, type BankSmsForm } from '@melorin/web-kit/bankSms.js';
import type { RequestBody, ResponseBody } from '@melorin/api-client';
import { API_BASE, typedClient } from '../../api/api.ts';
import { Empty, Field, Section, Switch, errMsg, num } from '../../shared/kit.tsx';
import { confirmDialog, dt } from '../../shared/ui.tsx';
import { useMainStore } from './usePaymentsData.ts';
import type { Toast } from '../../shared/types.ts';

const STATUS: Record<string, [string, string]> = {
  matched: ['شارژ شد', 'b-ok'],
  unmatched: ['در انتظار رسید', 'b-mu'],
  ambiguous: ['نیاز به بررسی', 'b-wn'],
  ignored: ['نادیده', 'b-mu'],
  unparsed: ['نامفهوم', 'b-bd'],
};
const SOURCE_PATH = '/api/v1/admin/stores/{store_id}/bank-sms/source' as const;
const OVERVIEW_PATH = '/api/v1/admin/stores/{store_id}/bank-sms' as const;
const TOKEN_PATH = '/api/v1/admin/stores/{store_id}/bank-sms/token' as const;
const RECONCILE_PATH = '/api/v1/admin/stores/{store_id}/bank-sms/reconcile' as const;
const IGNORE_PATH = '/api/v1/admin/stores/{store_id}/bank-sms/{sms_id}/ignore' as const;
const LINK_PATH = '/api/v1/admin/stores/{store_id}/bank-sms/{sms_id}/link' as const;

type Overview = ResponseBody<typeof OVERVIEW_PATH, 'get'>;
type SmsMessage = Overview['messages'][number];
type SourceBody = RequestBody<typeof SOURCE_PATH, 'put'>;
/** The slice of a payment row (GET /admin/payments) this panel needs to offer a pairing. */
export interface WaitingPayment {
  id: string;
  provider: string;
  status: string;
  has_receipt: boolean;
  currency: string;
  amount: number;
  created_at: string;
}
type TextField = Exclude<keyof BankSmsForm, 'auto_verify' | 'is_enabled' | 'require_claimed_time'>;

const isAbort = (e: unknown) => e instanceof DOMException && e.name === 'AbortError';

export default function BankSmsPanel({ toast, payments }: { toast: Toast; payments?: WaitingPayment[] | null }) {
  const client = useMemo(() => typedClient(API_BASE), []);
  const store = useMainStore(); // null = resolving, false = no main store
  const [data, setData] = useState<Overview | null>(null);
  const [form, setForm] = useState<BankSmsForm | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const [busy, setBusy] = useState('');
  const [tick, setTick] = useState(0);
  const reload = () => setTick((n) => n + 1);

  // The form is seeded from the stored source once and re-seeded only after a save: a reload (filter change, pairing,
  // reconcile) must never wipe what the admin is typing.
  const seed = (source: Overview['source']) => setForm(formFromSource(source));

  useEffect(() => {
    if (!store) return;
    const ctl = new AbortController();
    client
      .get(OVERVIEW_PATH, {
        params: { path: { store_id: store }, query: { status: filter || undefined } },
        signal: ctl.signal,
      })
      .then(({ data: d, response, error }) => {
        if (!response.ok || !d) return toast(errMsg(error, 'دریافت پیامک‌های بانک ناموفق بود'));
        setData(d);
        setForm((cur) => cur ?? formFromSource(d.source));
      })
      .catch((e) => !isAbort(e) && toast('ارتباط با سرور برقرار نشد'));
    return () => ctl.abort();
  }, [client, store, filter, tick, toast]);

  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    try {
      await fn();
    } catch {
      toast('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy('');
    }
  };
  const storePath = { store_id: String(store) };
  const save = () =>
    run('save', async () => {
      if (!form) return;
      const {
        data: d,
        response,
        error,
      } = await client.put(SOURCE_PATH, {
        params: { path: storePath },
        body: sourceBody(form) satisfies SourceBody,
      });
      if (!response.ok || !d) return toast(errMsg(error, 'ذخیره ناموفق بود'));
      if (d.token) setToken(d.token);
      seed(d.source);
      toast('تنظیمات ذخیره شد');
      reload();
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
      const { data: d, response, error } = await client.post(TOKEN_PATH, { params: { path: storePath } });
      if (!response.ok || !d) return toast(errMsg(error, 'تعویض توکن ناموفق بود'));
      setToken(d.token);
      reload();
    });
  const reconcile = () =>
    run('reconcile', async () => {
      const { data: d, response, error } = await client.post(RECONCILE_PATH, { params: { path: storePath } });
      if (!response.ok || !d) return toast(errMsg(error, 'بررسی دوباره ناموفق بود'));
      toast(d.matched ? `${num(d.matched)} پرداخت تطبیق و شارژ شد` : 'مورد جدیدی برای تطبیق نبود');
      reload();
    });
  const ignore = (m: SmsMessage, ignored: boolean) =>
    run(m.id, async () => {
      const { response, error } = await client.post(IGNORE_PATH, {
        params: { path: { ...storePath, sms_id: m.id } },
        body: { ignored },
      });
      if (!response.ok) return toast(errMsg(error, 'ناموفق بود'));
      reload();
    });
  const link = (m: SmsMessage, paymentId: string) =>
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
      const { response, error } = await client.post(LINK_PATH, {
        params: { path: { ...storePath, sms_id: m.id } },
        body: { payment_id: paymentId },
      });
      if (!response.ok) return toast(errMsg(error, 'اتصال ناموفق بود'));
      toast('پرداخت تأیید و کیف پول شارژ شد');
      reload();
    });

  if (store === false) return null;
  if (!store || !form || !data) return <div className="card skel h-24" />;
  const s = data.source;
  const live = s.configured && s.is_enabled && s.auto_verify;
  const set = (k: TextField) => (e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm({ ...form, [k]: e.target.value });
  const waiting = (payments || []).filter(
    (p) => p.provider === 'manual_card' && p.status === 'awaiting_review' && p.has_receipt,
  );
  const webhook = `${window.location.origin}/api/v1/payments/bank-sms/${s.store_id}`;

  return (
    <>
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
              onChange={(v: boolean) => setForm({ ...form, auto_verify: v })}
              label="شارژ خودکار"
            />
            شارژ خودکار پس از تطبیق
          </label>
          <label className="flex items-center gap-2 text-xs font-bold">
            <Switch
              checked={form.is_enabled}
              onChange={(v: boolean) => setForm({ ...form, is_enabled: v })}
              label="دریافت پیامک"
            />
            دریافت پیامک فعال
          </label>
          <label className="flex items-center gap-2 text-xs font-bold">
            <Switch
              checked={form.require_claimed_time}
              onChange={(v: boolean) => setForm({ ...form, require_claimed_time: v })}
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
          <Field label="شماره حساب (خط اول پیامک)" hint="اگر پر شود، پیامک حساب‌های دیگر نادیده گرفته می‌شود">
            <input
              dir="ltr"
              inputMode="numeric"
              className="inp"
              value={form.account_number}
              onChange={set('account_number')}
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
                      <th>شماره حساب</th>
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
    </>
  );
}
