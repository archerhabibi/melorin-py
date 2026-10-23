// پیام همگانی: the admin writes ONE message and picks who gets it. Core decides who is really reached (and enforces the daily
// limit); this screen only offers the groups Core returns, shows how many people each reaches, and tracks the delivery.
import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, Clock, Megaphone, RefreshCw, Send, Users } from 'lucide-react';
import { authFetch } from './api.js';
import { confirmDialog, dt } from './ui.jsx';
import { Empty, ErrorBar, Field, Section, errText, num, useRows } from './kit.jsx';

const TITLE_MAX = 120;
const BODY_MAX = 3500;

function AudienceCard({ a, on, onPick }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={on}
      onClick={() => onPick(a.id)}
      className={`card flex items-center justify-between gap-3 p-4 text-start transition ${on ? 'ring-2 ring-[var(--ac)]' : ''}`}
    >
      <span className="text-sm font-extrabold">{a.label}</span>
      <span className="badge b-mu">
        <Users size={13} /> {num(a.count)} نفر
      </span>
    </button>
  );
}

/** Delivery numbers of one sent message: sent / failed / no Telegram (inbox only) / still queued. */
export function DeliveryStats({ b }) {
  return (
    <div className="flex flex-wrap gap-2 text-xs">
      <span className="badge b-ok">
        <CheckCircle2 size={12} /> ارسال‌شده {num(b.sent)}
      </span>
      {b.queued > 0 && (
        <span className="badge b-wn">
          <Clock size={12} /> در صف {num(b.queued)}
        </span>
      )}
      {b.failed > 0 && (
        <span className="badge b-bd">
          <AlertTriangle size={12} /> ناموفق {num(b.failed)}
        </span>
      )}
      {b.no_telegram > 0 && <span className="badge b-mu">فقط صندوق پیام {num(b.no_telegram)}</span>}
    </div>
  );
}

export default function BroadcastView({ api, toast }) {
  const call = useCallback((p, o = {}) => authFetch(api.base, p, o), [api.base]);
  const hist = useRows(call, '/api/v1/admin/broadcasts');
  const [groups, setGroups] = useState([]);
  const [limit, setLimit] = useState(null);
  const [audFailed, setAudFailed] = useState(false);
  const [audience, setAudience] = useState('');
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  // { audiences: [{id, label, count}], daily_limit } - Core says which groups exist and how many people each reaches
  const loadAudiences = useCallback(async () => {
    try {
      const r = await call('/api/v1/admin/broadcasts/audiences');
      if (!r.ok) throw 0;
      const d = await r.json();
      setGroups(d.audiences || []);
      setLimit(d.daily_limit ?? null);
      setAudFailed(false);
    } catch {
      setAudFailed(true);
    }
  }, [call]);
  useEffect(() => {
    loadAudiences();
  }, [loadAudiences]);

  const items = hist.rows || [];
  const picked = groups.find((g) => g.id === audience);
  const queued = items.some((b) => b.queued > 0);

  // while messages are still being delivered keep the numbers fresh
  useEffect(() => {
    if (!queued) return undefined;
    const t = setInterval(hist.load, 8000);
    return () => clearInterval(t);
  }, [queued, hist.load]);

  const ready = picked && picked.count > 0 && title.trim() && body.trim() && !busy;

  const send = async () => {
    setError('');
    const ok = await confirmDialog(
      `«${title.trim()}» برای ${num(picked.count)} نفر (${picked.label}) ارسال شود؟ پس از ارسال قابل بازگرداندن نیست.`,
      { title: 'ارسال پیام همگانی', ok: 'ارسال' },
    );
    if (!ok) return;
    setBusy(true);
    try {
      const r = await call('/api/v1/admin/broadcasts', {
        method: 'POST',
        body: JSON.stringify({ audience, title: title.trim(), body: body.trim() }),
      });
      if (!r.ok) setError(await errText(r, 'ارسال ناموفق بود'));
      else {
        const d = await r.json();
        toast(`پیام برای ${num(d.recipients)} نفر در صف ارسال قرار گرفت`);
        setTitle('');
        setBody('');
        await Promise.all([hist.load(), loadAudiences()]);
      }
    } catch {
      setError('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <Section
        title="گیرندگان"
        hint="هر پیام فقط داخل فروشگاه خود گیرنده نمایش داده می‌شود؛ مشتری نماینده، پیام را از ربات و سایت همان نماینده می‌گیرد."
      >
        {audFailed && <ErrorBar onRetry={loadAudiences}>دریافت گروه‌های گیرنده ناموفق بود.</ErrorBar>}
        <div role="radiogroup" aria-label="گروه گیرنده" className="grid gap-3 sm:grid-cols-2">
          {groups.map((g) => (
            <AudienceCard key={g.id} a={g} on={audience === g.id} onPick={setAudience} />
          ))}
        </div>
      </Section>

      <Section title="متن پیام" hint={limit ? `حداکثر ${num(limit)} پیام همگانی در هر ۲۴ ساعت.` : undefined}>
        <div className="space-y-4">
          <Field label="عنوان" hint={`${num(title.length)} / ${num(TITLE_MAX)}`}>
            <input className="inp" maxLength={TITLE_MAX} value={title} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <Field label="متن" hint={`${num(body.length)} / ${num(BODY_MAX)}`}>
            <textarea
              className="inp"
              rows={6}
              maxLength={BODY_MAX}
              value={body}
              onChange={(e) => setBody(e.target.value)}
            />
          </Field>
          {error && <ErrorBar>{error}</ErrorBar>}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-xs text-[var(--mu)]">
              {picked ? `${num(picked.count)} نفر · ${picked.label}` : 'یک گروه گیرنده انتخاب کنید'}
            </span>
            <button className="btn" disabled={!ready} onClick={send}>
              <Send size={15} /> {busy ? 'در حال ارسال…' : 'ارسال پیام'}
            </button>
          </div>
        </div>
      </Section>

      <Section title="پیام‌های ارسال‌شده">
        <button className="btn btn-g mb-3" onClick={hist.load}>
          <RefreshCw size={14} /> به‌روزرسانی
        </button>
        {hist.failed && <ErrorBar onRetry={hist.load}>دریافت سابقه ناموفق بود.</ErrorBar>}
        {hist.rows && !items.length ? (
          <Empty
            Icon={Megaphone}
            title="هنوز پیامی ارسال نشده"
            text="پیام‌های همگانی شما همراه با وضعیت تحویل اینجا نمایش داده می‌شود."
          />
        ) : (
          <div className="grid gap-3">
            {items.map((b) => (
              <article key={b.id} className="card space-y-2 p-4">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <h4 className="text-sm font-extrabold">{b.title}</h4>
                  <span className="text-xs text-[var(--mu)]">
                    {b.audience_label} · {num(b.recipients)} نفر · {dt(b.created_at)}
                  </span>
                </div>
                <p className="whitespace-pre-line text-sm leading-7">{b.body}</p>
                <DeliveryStats b={b} />
              </article>
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}
