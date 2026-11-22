import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, Undo2 } from 'lucide-react';
import { Empty, Field, Section, Switch, errText, num } from '../../shared/kit.tsx';
import { confirmDialog, dt } from '../../shared/ui.tsx';
import ReceiptDuplicatePolicy from './ReceiptDuplicatePolicy.tsx';
import { openBlobInTab } from './receiptFile.ts';
import type { ReceiptFetcher } from './receiptFile.ts';
import type { CallFn, Json, Toast } from '../../shared/types.ts';
import { JSON_H, CUR, toInt, clock } from './receiptHelpers';
import { Row } from './ReceiptRow';

export default function ReceiptReviewPanel({
  call,
  toast,
  base,
  receipt,
  onChanged,
}: {
  call: CallFn;
  toast: Toast;
  base?: string;
  receipt?: ReceiptFetcher;
  onChanged?: Json;
}) {
  const [data, setData] = useState<Json>(null);
  const [form, setForm] = useState<Json>(null);
  const [busy, setBusy] = useState('');
  const [failed, setFailed] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const skew = useRef(0);

  const apply = useCallback((d: Json) => {
    setData(d);
    skew.current = d.now ? new Date(d.now).getTime() - Date.now() : 0;
    setNow(Date.now() + skew.current); // sync the clock immediately, not on the next 1s tick
    setForm(
      (f: Json) =>
        f || {
          enabled: !!d.config.enabled,
          minutes: d.config.minutes,
          max_amount_rial: String(d.config.max_amount_rial),
          max_exposure_rial: String(d.config.max_exposure_rial),
          max_open_per_user: String(d.config.max_open_per_user),
          max_open_per_origin: String(d.config.max_open_per_origin ?? 2),
        },
    );
  }, []);
  const load = useCallback(async () => {
    if (!base) return;
    try {
      const r = await call(`${base}/receipt-review`);
      if (!r.ok) {
        setFailed(true);
        return toast(await errText(r, 'دریافت صف بازبینی ناموفق بود'));
      }
      const d = await r.json();
      if (!d?.config) return setFailed(true); // an older server without this feature: show nothing instead of breaking the page
      setFailed(false);
      apply(d);
    } catch {
      /* transient: the next poll retries */
    }
  }, [apply, base, call, toast]);
  useEffect(() => {
    load();
    const poll = setInterval(load, 15000);
    return () => clearInterval(poll);
  }, [load]);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now() + skew.current), 1000);
    return () => clearInterval(t);
  }, []);

  const run = async (key: Json, fn: Json) => {
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
        enabled: form.enabled,
        minutes: Number(form.minutes),
        max_amount_rial: toInt(form.max_amount_rial),
        max_exposure_rial: toInt(form.max_exposure_rial),
        max_open_per_user: toInt(form.max_open_per_user),
        max_open_per_origin: toInt(form.max_open_per_origin),
      };
      const r = await call(`${base}/receipt-review/settings`, {
        method: 'PUT',
        headers: JSON_H,
        body: JSON.stringify(body),
      });
      if (!r.ok) return toast(await errText(r, 'ذخیره ناموفق بود'));
      toast(form.enabled ? 'تأیید موقت فعال شد' : 'تنظیمات ذخیره شد');
      setForm(null);
      load();
    });
  const decide = (item: Json, approve: Json, provisional: Json) =>
    run(item.payment_id, async () => {
      const ok = await confirmDialog(
        approve
          ? provisional
            ? 'شارژ موقت نهایی شود؟ پس از این، اعتبار مشتری ثابت می‌ماند.'
            : 'این رسید تأیید و کیف پول مشتری شارژ شود؟'
          : provisional
            ? 'شارژ موقت لغو و اعتبار از کیف پول برگردانده شود؟ اگر مشتری خرجش کرده باشد، کیف پول منفی می‌شود.'
            : 'این رسید رد شود؟',
        {
          title: approve ? 'تأیید رسید' : provisional ? 'لغو شارژ موقت' : 'رد رسید',
          ok: approve ? 'تأیید' : provisional ? 'لغو و برگشت اعتبار' : 'رد رسید',
          danger: !approve,
        },
      );
      if (!ok) return;
      const r = await call(`${base}/receipt-review/${item.payment_id}`, {
        method: 'POST',
        headers: JSON_H,
        body: JSON.stringify({ approve }),
      });
      if (!r.ok) return toast(await errText(r, 'ثبت تصمیم ناموفق بود'));
      toast(approve ? 'تأیید شد' : provisional ? 'شارژ موقت لغو شد' : 'رسید رد شد');
      load();
      onChanged?.();
    });
  const viewReceipt = async (item: Json) => {
    if (!receipt) return;
    try {
      const r = await receipt(String(item.payment_id));
      if (!r.ok) return toast(await errText(r, 'نمایش رسید ناموفق بود'));
      openBlobInTab(await r.blob());
    } catch {
      toast('ارتباط با سرور برقرار نشد');
    }
  };

  if (failed && !data) return null;
  if (!data || !form) return <div className="card skel h-24" />;
  const c = data.config;
  const exposurePct = Math.min(100, (data.exposure_rial / c.max_exposure_rial) * 100);
  const prov = data.provisional;
  const dirty =
    form.enabled !== !!c.enabled ||
    Number(form.minutes) !== c.minutes ||
    toInt(form.max_amount_rial) !== c.max_amount_rial ||
    toInt(form.max_exposure_rial) !== c.max_exposure_rial ||
    toInt(form.max_open_per_user) !== c.max_open_per_user ||
    toInt(form.max_open_per_origin) !== (c.max_open_per_origin ?? 2);

  return (
    <Section
      title="بازبینی سریع و تأیید موقت رسیدها"
      hint="مشتری نباید منتظر آنلاین‌شدن ادمین بماند. اگر رسید مبهم تا چند دقیقه بررسی نشود، شارژ موقت می‌شود و در صف بازبینی فوری می‌ماند."
    >
      <ol className="grid gap-2 text-xs sm:grid-cols-4" aria-label="جریان تأیید">
        {[
          ['رسید مبهم', 'به بررسی دستی می‌رود'],
          [`${num(c.minutes)} دقیقه مهلت`, 'ادمین یا نماینده تصمیم بگیرد'],
          ['شارژ موقت', c.enabled ? 'خودکار و با سقف' : 'غیرفعال است'],
          ['بازبینی فوری', 'تأیید نهایی یا لغو و برگشت اعتبار'],
        ].map(([t, s], i) => (
          <li key={t} className="rounded-xl bg-[var(--bg2)] p-3">
            <span className="text-[11px] text-[var(--mu)]">{num(i + 1)}</span>
            <div className="font-extrabold">{t}</div>
            <div className="text-[11px] leading-5 text-[var(--mu)]">{s}</div>
          </li>
        ))}
      </ol>

      <ReceiptDuplicatePolicy key={base} toast={toast} base={base} />

      <details className="group rounded-xl border border-[var(--ln)]" open={!c.enabled}>
        <summary className="flex cursor-pointer list-none items-center justify-between gap-2 p-3 text-xs font-extrabold">
          <span className="flex items-center gap-2">
            تنظیمات
            <span className={`badge ${c.enabled ? 'b-ok' : 'b-mu'}`}>{c.enabled ? 'تأیید موقت فعال' : 'غیرفعال'}</span>
          </span>
        </summary>
        <div className="space-y-4 border-t border-[var(--ln)] p-3">
          <label className="flex items-center gap-2 text-xs font-bold">
            <Switch
              checked={form.enabled}
              onChange={(v: Json) => setForm({ ...form, enabled: v })}
              label="تأیید موقت"
            />
            فعال‌سازی تأیید موقت پس از مهلت
          </label>
          <Field
            label={`مهلت بررسی دستی: ${num(form.minutes)} دقیقه`}
            hint={`اگر تا ${num(form.minutes)} دقیقه بعد از ارسال رسید کسی تصمیم نگیرد، شارژ موقت می‌شود.`}
          >
            <input
              type="range"
              min={1}
              max={60}
              value={form.minutes}
              onChange={(e) => setForm({ ...form, minutes: Number(e.target.value) })}
              className="w-full"
              aria-label="مهلت بررسی دستی به دقیقه"
            />
          </Field>
          <div className="grid gap-3 md:grid-cols-3">
            <Field label="سقف هر رسید (ریال)" hint="رسید بالاتر هرگز موقت تأیید نمی‌شود">
              <input
                dir="ltr"
                inputMode="numeric"
                className="inp"
                value={form.max_amount_rial}
                onChange={(e) => setForm({ ...form, max_amount_rial: e.target.value })}
              />
            </Field>
            <Field label="سقف کل اعتبار موقت باز (ریال)" hint="جمع شارژهای موقتِ بازبینی‌نشده">
              <input
                dir="ltr"
                inputMode="numeric"
                className="inp"
                value={form.max_exposure_rial}
                onChange={(e) => setForm({ ...form, max_exposure_rial: e.target.value })}
              />
            </Field>
            <Field label="حداکثر موقت باز برای هر مشتری" hint="مشتری با اعتبار موقت لغوشده دیگر شامل نمی‌شود">
              <input
                dir="ltr"
                inputMode="numeric"
                className="inp"
                value={form.max_open_per_user}
                onChange={(e) => setForm({ ...form, max_open_per_user: e.target.value })}
              />
            </Field>
            <Field label="حداکثر موقت باز برای هر شبکه" hint="چند حساب تازه از یک شبکه نمی‌توانند سقف را دور بزنند">
              <input
                dir="ltr"
                inputMode="numeric"
                className="inp"
                value={form.max_open_per_origin}
                onChange={(e) => setForm({ ...form, max_open_per_origin: e.target.value })}
              />
            </Field>
          </div>
          <p className="rounded-lg bg-[var(--bg2)] p-2 text-[11px] leading-6">
            <b>ایمنی:</b> رسیدی که مبلغ خوانده‌شده‌اش با درخواست فرق دارد، تصویر یا شماره مرجع تکراری دارد، یا مشتری‌اش
            قبلاً شارژ موقت لغوشده داشته، هرگز موقت تأیید نمی‌شود. اگر پیامک بانک بعداً برسد، شارژ موقت خودکار نهایی
            می‌شود.
          </p>
          <button className="btn btn-p" disabled={busy === 'save' || !dirty} onClick={save}>
            ذخیره
          </button>
        </div>
      </details>

      {c.enabled && (
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <span className="font-bold">اعتبار موقت باز:</span>
          <b>{num(data.exposure_rial)} ریال</b>
          <span className="text-[var(--mu)]">از سقف {num(c.max_exposure_rial)}</span>
          <div
            className="h-1.5 w-32 overflow-hidden rounded-full bg-[var(--bg2)]"
            role="progressbar"
            aria-valuenow={Math.round(exposurePct)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="مصرف سقف اعتبار موقت"
          >
            <div
              className={`h-full rounded-full ${exposurePct > 80 ? 'bg-[var(--bd)]' : 'bg-[var(--ok)]'}`}
              style={{ width: `${exposurePct}%` }}
            />
          </div>
        </div>
      )}

      <div aria-live="polite" className="space-y-5">
        <div className="space-y-2">
          <h4 className="flex items-center gap-2 text-xs font-extrabold">
            شارژهای موقتِ منتظر بازبینی فوری
            {prov.length > 0 && <span className="badge b-wn">{num(prov.length)}</span>}
          </h4>
          {!prov.length ? (
            <Empty
              Icon={Check}
              title="موردی برای بازبینی فوری نیست"
              text="شارژهای موقت اینجا نمایش داده می‌شوند تا نهایی یا لغو شوند."
            />
          ) : (
            <ul className="space-y-2">
              {prov.map((i: Json) => (
                <Row
                  key={i.payment_id}
                  item={i}
                  tone="wn"
                  now={now}
                  minutes={c.minutes}
                  onReceipt={receipt && viewReceipt}
                >
                  <button
                    className="btn btn-p !py-1.5"
                    disabled={busy === i.payment_id}
                    onClick={() => decide(i, true, true)}
                  >
                    <Check size={14} /> تأیید نهایی
                  </button>
                  <button
                    className="btn btn-g !py-1.5"
                    disabled={busy === i.payment_id}
                    onClick={() => decide(i, false, true)}
                  >
                    <Undo2 size={14} /> لغو و برگشت اعتبار
                  </button>
                </Row>
              ))}
            </ul>
          )}
        </div>

        <div className="space-y-2">
          <h4 className="flex items-center gap-2 text-xs font-extrabold">
            رسیدهای در انتظار بررسی دستی
            {data.waiting.length > 0 && <span className="badge b-in">{num(data.waiting.length)}</span>}
          </h4>
          {!data.waiting.length ? (
            <Empty
              Icon={Check}
              title="رسید منتظری نیست"
              text="رسیدهای مبهم اینجا با شمارنده‌ی مهلت نمایش داده می‌شوند."
            />
          ) : (
            <ul className="space-y-2">
              {data.waiting.map((i: Json) => (
                <Row
                  key={i.payment_id}
                  item={i}
                  tone="ln"
                  now={now}
                  minutes={c.minutes}
                  onReceipt={receipt && viewReceipt}
                >
                  <button
                    className="btn btn-p !py-1.5"
                    disabled={busy === i.payment_id}
                    onClick={() => decide(i, true, false)}
                  >
                    تأیید
                  </button>
                  <button
                    className="btn btn-g !py-1.5"
                    disabled={busy === i.payment_id}
                    onClick={() => decide(i, false, false)}
                  >
                    رد
                  </button>
                </Row>
              ))}
            </ul>
          )}
        </div>

        {data.recent.length > 0 && (
          <details className="rounded-xl border border-[var(--ln)]">
            <summary className="cursor-pointer p-3 text-xs font-extrabold">
              تصمیم‌های اخیر ({num(data.recent.length)})
            </summary>
            <ul className="space-y-1 border-t border-[var(--ln)] p-3 text-xs">
              {data.recent.map((i: Json) => (
                <li key={i.payment_id} className="flex flex-wrap items-center justify-between gap-2">
                  <span>
                    {num(i.amount)} {CUR[i.currency] || i.currency}
                  </span>
                  <span className={`badge ${i.state === 'confirmed' ? 'b-ok' : 'b-bd'}`}>
                    {i.state === 'confirmed'
                      ? i.resolved_by === 'bank_sms'
                        ? 'نهایی با پیامک بانک'
                        : 'نهایی شد'
                      : 'لغو شد'}
                  </span>
                  <span className="text-[11px] text-[var(--mu)]">{i.resolved_at ? dt(i.resolved_at) : ''}</span>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </Section>
  );
}
