// پیام همگانی (reseller): a reseller writes one message to the customers of HIS OWN store. Core decides who is reached
// (his store's customers only, never another store's people) and enforces the daily limit; this tab shows Core's numbers.
import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, Clock, Megaphone, RefreshCw, Send, Users } from 'lucide-react';
import { Empty, Loading, fa, fd } from './ui.jsx';

const J = { 'Content-Type': 'application/json' };
const TITLE_MAX = 120;
const BODY_MAX = 3500;
const chip = 'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-bold';

function Delivery({ b }) {
  return (
    <div className="flex flex-wrap gap-2">
      <span className={`${chip} bg-mint-soft text-mint`}>
        <CheckCircle2 size={13} /> ارسال‌شده {fa(b.sent)}
      </span>
      {b.queued > 0 && (
        <span className={`${chip} bg-accent-soft text-ink`}>
          <Clock size={13} /> در صف {fa(b.queued)}
        </span>
      )}
      {b.failed > 0 && (
        <span className={`${chip} bg-danger-soft text-danger`}>
          <AlertTriangle size={13} /> ناموفق {fa(b.failed)}
        </span>
      )}
      {b.no_telegram > 0 && (
        <span className={`${chip} bg-surface2 text-muted`}>فقط صندوق پیام {fa(b.no_telegram)}</span>
      )}
    </div>
  );
}

export default function ResellerBroadcast({ coreFetch, base, notify }) {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const r = await coreFetch(`${base}/broadcasts`);
      if (!r.ok) throw 0;
      setData(await r.json());
      setFailed(false);
    } catch {
      setFailed(true);
      setData((x) => x || { audiences: [], items: [], daily_limit: null });
    }
  }, [coreFetch, base]);
  useEffect(() => {
    load();
  }, [load]);

  const items = data?.items || [];
  const reach = data?.audiences?.[0]?.count ?? 0;
  const queued = items.some((b) => b.queued > 0);
  // keep the delivery numbers fresh while messages are still going out
  useEffect(() => {
    if (!queued) return undefined;
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, [queued, load]);

  if (data === null) return <Loading rows={3} />;
  const ready = title.trim() && body.trim() && reach > 0 && !busy;

  const send = async () => {
    setError('');
    if (
      !window.confirm(
        `«${title.trim()}» برای ${fa(reach)} مشتری فروشگاه شما ارسال شود؟ پس از ارسال قابل بازگرداندن نیست.`,
      )
    )
      return;
    setBusy(true);
    try {
      const r = await coreFetch(`${base}/broadcasts`, {
        method: 'POST',
        headers: J,
        body: JSON.stringify({ title: title.trim(), body: body.trim() }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setError(d?.error?.message || (typeof d?.detail === 'string' ? d.detail : '') || 'ارسال ناموفق بود');
      } else {
        const d = await r.json();
        notify(`پیام برای ${fa(d.recipients)} مشتری در صف ارسال قرار گرفت`);
        setTitle('');
        setBody('');
        await load();
      }
    } catch {
      setError('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <section className="card space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="flex items-center gap-2 text-base font-extrabold">
            <Megaphone size={18} /> پیام همگانی به مشتریان
          </h3>
          <span className={`${chip} bg-surface2 text-muted`}>
            <Users size={13} /> {fa(reach)} مشتری فعال
          </span>
        </div>
        <p className="text-sm leading-7 text-muted">
          پیام فقط برای مشتریان فروشگاه شما ارسال می‌شود و از طریق ربات و صندوق پیام همین فروشگاه به آن‌ها می‌رسد.
          {data.daily_limit ? ` حداکثر ${fa(data.daily_limit)} پیام همگانی در هر ۲۴ ساعت.` : ''}
        </p>
        <label className="block text-sm font-bold">
          عنوان
          <input
            className="input mt-1.5 !py-2.5"
            maxLength={TITLE_MAX}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <span className="mt-1 block text-xs font-normal text-muted">
            {fa(title.length)} / {fa(TITLE_MAX)}
          </span>
        </label>
        <label className="block text-sm font-bold">
          متن پیام
          <textarea
            className="input mt-1.5"
            rows={6}
            maxLength={BODY_MAX}
            value={body}
            onChange={(e) => setBody(e.target.value)}
          />
          <span className="mt-1 block text-xs font-normal text-muted">
            {fa(body.length)} / {fa(BODY_MAX)}
          </span>
        </label>
        {(error || failed) && (
          <p role="alert" className="rounded-xl bg-danger-soft p-3 text-sm text-danger">
            {error || 'دریافت اطلاعات ناموفق بود.'}
          </p>
        )}
        <div className="flex justify-end">
          <button className="btn-primary !py-2.5" disabled={!ready} onClick={send}>
            <Send size={16} /> {busy ? 'در حال ارسال…' : 'ارسال پیام'}
          </button>
        </div>
      </section>

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-extrabold">پیام‌های ارسال‌شده</h3>
          <button className="btn-ghost" onClick={load}>
            <RefreshCw size={15} /> به‌روزرسانی
          </button>
        </div>
        {!items.length ? (
          <Empty text="هنوز پیام همگانی‌ای ارسال نکرده‌اید" icon={Megaphone} />
        ) : (
          items.map((b) => (
            <article key={b.id} className="card space-y-2">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <h4 className="font-extrabold">{b.title}</h4>
                <span className="text-xs text-muted">
                  {fa(b.recipients)} مشتری · {fd(b.created_at)}
                </span>
              </div>
              <p className="whitespace-pre-line text-sm leading-7">{b.body}</p>
              <Delivery b={b} />
            </article>
          ))
        )}
      </section>
    </div>
  );
}
