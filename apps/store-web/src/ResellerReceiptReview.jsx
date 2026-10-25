// بازبینی سریع و تأیید موقت رسیدها (reseller). An unclear receipt waits for the owner; if nobody decides within N minutes
// Core credits the customer provisionally and the payment stays here until the owner confirms (credit stays) or revokes
// it (credit is reversed). Core enforces every cap; this panel edits the settings, shows the live countdown and decides.
import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, Check, Hourglass, Undo2 } from 'lucide-react';
import { Loading, fa, fd } from './ui.jsx';

const J = { 'Content-Type': 'application/json' };
const CUR = { IRT: 'تومان', IRR: 'ریال' };
const chip = 'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-bold';
const toInt = (s) => {
  const t = String(s ?? '')
    .replace(/[۰-۹]/g, (d) => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d))
    .replace(/\D/g, '');
  return t === '' ? null : Number(t);
};
export const clock = (sec) => {
  const s = Math.max(0, Math.floor(sec));
  return `${fa(Math.floor(s / 60)).padStart(2, '۰')}:${fa(s % 60).padStart(2, '۰')}`;
};
async function message(r, fallback) {
  const d = await r.json().catch(() => ({}));
  return d?.error?.message || fallback;
}

function Facts({ r }) {
  const rows = r
    ? [
        ['مبلغ رسید', r.amount_rial ? `${fa(r.amount_rial)} ریال` : null],
        ['زمان', r.paid_at ? fd(r.paid_at) : null],
        ['کارت مبدأ', r.source_card_last4 ? `…${r.source_card_last4}` : null],
        ['مرجع', r.reference],
      ].filter(([, v]) => v)
    : [];
  if (!rows.length) return <span className="text-xs text-muted">رسید خوانده نشد؛ بررسی چشمی لازم است</span>;
  return (
    <span className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted">
      {rows.map(([k, v]) => (
        <span key={k}>
          {k}: <b dir="ltr">{v}</b>
        </span>
      ))}
    </span>
  );
}

function Item({ item, now, minutes, children }) {
  const left = item.auto_approve_at ? (new Date(item.auto_approve_at).getTime() - now) / 1000 : null;
  const total = (minutes || 5) * 60;
  const pct = left == null ? 0 : Math.min(100, Math.max(0, ((total - left) / total) * 100));
  return (
    <li className={`rounded-2xl border p-3 ${item.state === 'open' ? 'border-danger/40' : 'border-line'}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <b>
            {fa(item.amount)} {CUR[item.currency] || item.currency}
          </b>
          {item.block_text && (
            <div className="flex items-center gap-1 text-xs text-danger">
              <AlertTriangle size={13} /> تأیید موقت نمی‌شود: {item.block_text}
            </div>
          )}
          {item.shortfall ? <div className="text-xs text-danger">کسری کیف پول: {fa(item.shortfall)}</div> : null}
          <div>
            <Facts r={item.receipt_read} />
          </div>
        </div>
        <div className="flex flex-wrap gap-2">{children}</div>
      </div>
      {left != null && !item.block && (
        <div className="mt-2">
          <div className="mb-1 flex items-center justify-between text-xs text-muted">
            <span className="flex items-center gap-1">
              <Hourglass size={12} /> {left > 0 ? 'تا تأیید موقت' : 'در حال تأیید موقت…'}
            </span>
            <b dir="ltr">{clock(left)}</b>
          </div>
          <div
            className="h-1.5 overflow-hidden rounded-full bg-surface2"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(pct)}
            aria-label="زمان باقی‌مانده تا تأیید موقت"
          >
            <div
              className="h-full rounded-full bg-danger transition-[width] duration-1000"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
      )}
    </li>
  );
}

export default function ResellerReceiptReview({ coreFetch, base, notify }) {
  const url = `${base}/receipt-review`;
  const [data, setData] = useState(null);
  const [form, setForm] = useState(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState('');
  const [now, setNow] = useState(() => Date.now());
  const skew = useRef(0);

  const load = useCallback(async () => {
    try {
      const r = await coreFetch(url);
      const d = r.ok ? await r.json() : null;
      if (!d?.config) return setFailed(true);
      setFailed(false);
      skew.current = d.now ? new Date(d.now).getTime() - Date.now() : 0;
      setData(d);
      setForm(
        (f) =>
          f || {
            enabled: !!d.config.enabled,
            minutes: d.config.minutes,
            max_amount_rial: String(d.config.max_amount_rial),
            max_exposure_rial: String(d.config.max_exposure_rial),
            max_open_per_user: String(d.config.max_open_per_user),
          },
      );
    } catch {
      /* the next poll retries */
    }
  }, [coreFetch, url]);
  useEffect(() => {
    load();
    const poll = setInterval(load, 15000);
    return () => clearInterval(poll);
  }, [load]);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now() + skew.current), 1000);
    return () => clearInterval(t);
  }, []);

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
        enabled: form.enabled,
        minutes: Number(form.minutes),
        max_amount_rial: toInt(form.max_amount_rial),
        max_exposure_rial: toInt(form.max_exposure_rial),
        max_open_per_user: toInt(form.max_open_per_user),
      };
      const r = await coreFetch(`${url}/settings`, { method: 'PUT', headers: J, body: JSON.stringify(body) });
      if (!r.ok) return notify(await message(r, 'ذخیره ناموفق بود'));
      notify(form.enabled ? 'تأیید موقت فعال شد' : 'تنظیمات ذخیره شد');
      setForm(null);
      load();
    });
  const decide = (item, approve, provisional) =>
    run(item.payment_id, async () => {
      const text = approve
        ? provisional
          ? 'شارژ موقت نهایی شود؟'
          : 'این رسید تأیید و کیف پول مشتری شارژ شود؟'
        : provisional
          ? 'شارژ موقت لغو و اعتبار برگردانده شود؟ اگر مشتری خرجش کرده باشد، کیف پول منفی می‌شود.'
          : 'این رسید رد شود؟';
      if (!window.confirm(text)) return;
      const r = await coreFetch(`${url}/${item.payment_id}`, {
        method: 'POST',
        headers: J,
        body: JSON.stringify({ approve }),
      });
      if (!r.ok) return notify(await message(r, 'ثبت تصمیم ناموفق بود'));
      notify(approve ? 'تأیید شد' : provisional ? 'شارژ موقت لغو شد' : 'رسید رد شد');
      load();
    });

  if (failed && !data) return null;
  if (!data || !form) return <Loading rows={2} />;
  const c = data.config;
  const dirty =
    form.enabled !== !!c.enabled ||
    Number(form.minutes) !== c.minutes ||
    toInt(form.max_amount_rial) !== c.max_amount_rial ||
    toInt(form.max_exposure_rial) !== c.max_exposure_rial ||
    toInt(form.max_open_per_user) !== c.max_open_per_user;
  const field = (k, label, hint) => (
    <label className="text-xs font-bold">
      {label}
      <input
        dir="ltr"
        inputMode="numeric"
        className="input mt-1 !py-2.5"
        value={form[k]}
        onChange={(e) => setForm({ ...form, [k]: e.target.value })}
      />
      <span className="mt-1 block font-normal text-muted">{hint}</span>
    </label>
  );

  return (
    <div className="card space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h4 className="flex items-center gap-2 font-extrabold">
          <Hourglass size={18} /> بازبینی سریع و تأیید موقت رسیدها
        </h4>
        <span className={`${chip} ${c.enabled ? 'bg-mint/15 text-mint' : 'bg-surface2 text-muted'}`}>
          {c.enabled ? `تأیید موقت پس از ${fa(c.minutes)} دقیقه` : 'غیرفعال'}
        </span>
      </div>
      <p className="text-xs leading-6 text-muted">
        مشتری نباید منتظر آنلاین‌شدن شما بماند. اگر رسید مبهم تا {fa(form.minutes)} دقیقه بررسی نشود، شارژ موقت می‌شود و
        اینجا برای تأیید نهایی یا لغو می‌ماند. رسیدی که مبلغش با درخواست فرق دارد یا تصویر/مرجعش تکراری است هرگز موقت
        تأیید نمی‌شود.
      </p>
      <details className="rounded-2xl border border-line p-3" open={!c.enabled}>
        <summary className="cursor-pointer text-sm font-bold">تنظیمات</summary>
        <div className="mt-3 space-y-3">
          <label className="flex items-center gap-2 text-sm font-bold">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
            />
            فعال‌سازی تأیید موقت پس از مهلت
          </label>
          <label className="block text-xs font-bold">
            مهلت بررسی دستی: {fa(form.minutes)} دقیقه
            <input
              type="range"
              min={1}
              max={60}
              className="mt-1 w-full"
              aria-label="مهلت بررسی دستی به دقیقه"
              value={form.minutes}
              onChange={(e) => setForm({ ...form, minutes: Number(e.target.value) })}
            />
          </label>
          <div className="grid gap-3 md:grid-cols-3">
            {field('max_amount_rial', 'سقف هر رسید (ریال)', 'بالاتر از آن همیشه دستی')}
            {field('max_exposure_rial', 'سقف کل اعتبار موقت باز (ریال)', 'جمع شارژهای موقتِ بازبینی‌نشده')}
            {field('max_open_per_user', 'حداکثر موقت باز برای هر مشتری', 'مشتری با لغو قبلی شامل نمی‌شود')}
          </div>
          <button className="btn" disabled={busy === 'save' || !dirty} onClick={save}>
            ذخیره
          </button>
        </div>
      </details>

      <div aria-live="polite" className="space-y-4">
        <div className="space-y-2">
          <h5 className="text-sm font-extrabold">شارژهای موقتِ منتظر بازبینی فوری ({fa(data.provisional.length)})</h5>
          {!data.provisional.length ? (
            <p className="text-xs text-muted">موردی نیست.</p>
          ) : (
            <ul className="space-y-2">
              {data.provisional.map((i) => (
                <Item key={i.payment_id} item={i} now={now} minutes={c.minutes}>
                  <button className="btn" disabled={busy === i.payment_id} onClick={() => decide(i, true, true)}>
                    <Check size={14} /> تأیید نهایی
                  </button>
                  <button className="btn-ghost" disabled={busy === i.payment_id} onClick={() => decide(i, false, true)}>
                    <Undo2 size={14} /> لغو و برگشت اعتبار
                  </button>
                </Item>
              ))}
            </ul>
          )}
        </div>
        <div className="space-y-2">
          <h5 className="text-sm font-extrabold">رسیدهای در انتظار بررسی ({fa(data.waiting.length)})</h5>
          {!data.waiting.length ? (
            <p className="text-xs text-muted">رسید منتظری نیست.</p>
          ) : (
            <ul className="space-y-2">
              {data.waiting.map((i) => (
                <Item key={i.payment_id} item={i} now={now} minutes={c.minutes}>
                  <button className="btn" disabled={busy === i.payment_id} onClick={() => decide(i, true, false)}>
                    تأیید
                  </button>
                  <button
                    className="btn-ghost"
                    disabled={busy === i.payment_id}
                    onClick={() => decide(i, false, false)}
                  >
                    رد
                  </button>
                </Item>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
