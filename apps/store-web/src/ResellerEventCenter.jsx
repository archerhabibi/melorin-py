// مرکز رویداد تلگرام (reseller): the owner connects a Telegram supergroup (with Topics) for HIS store's events only. Messages
// are sent with the store's OWN bot, never the main bot. Core validates and sends; this tab edits settings and shows health.
import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, BellRing, CheckCircle2, ListPlus, ScanSearch, Send, Trash2 } from 'lucide-react';
import { Loading, fd } from './ui.jsx';

const J = { 'Content-Type': 'application/json' };
const chip = 'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-bold';
const toEn = (s) =>
  String(s ?? '')
    .replace(/[۰-۹]/g, (d) => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d))
    .replace(/[٠-٩]/g, (d) => '٠١٢٣٤٥٦٧٨٩'.indexOf(d))
    .replace(/\D/g, '');

async function message(r, fallback) {
  const d = await r.json().catch(() => ({}));
  return d?.error?.message || (typeof d?.detail === 'string' ? d.detail : '') || fallback;
}

export default function ResellerEventCenter({ coreFetch, base, notify }) {
  const url = `${base}/event-center`;
  const [data, setData] = useState(null);
  const [chat, setChat] = useState('');
  const [threads, setThreads] = useState({});
  const [enabled, setEnabled] = useState(true);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [results, setResults] = useState(null);
  const [check, setCheck] = useState(null);
  const [made, setMade] = useState(null);

  const apply = (d) => {
    setData(d);
    setChat(d.chat_id || '');
    setEnabled(d.is_enabled !== false);
    setNote(d.note || '');
    setThreads(Object.fromEntries((d.topics || []).map((t) => [t.key, t.thread_id ? String(t.thread_id) : ''])));
  };
  const load = useCallback(async () => {
    try {
      const r = await coreFetch(url);
      if (!r.ok) throw 0;
      apply(await r.json());
    } catch {
      setError('دریافت تنظیمات ناموفق بود');
      setData((x) => x || { configured: false, bot_ready: true, topics: [] });
    }
  }, [coreFetch, url]);
  useEffect(() => {
    load();
  }, [load]);

  const act = async (name, fn) => {
    setError('');
    setBusy(name);
    try {
      await fn();
    } catch {
      setError('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy('');
    }
  };

  const save = () =>
    act('save', async () => {
      const topics = Object.fromEntries(Object.entries(threads).map(([k, v]) => [k, toEn(v)]));
      const r = await coreFetch(url, {
        method: 'PUT',
        headers: J,
        body: JSON.stringify({ chat_id: chat.trim(), topics, is_enabled: enabled, note: note.trim() || null }),
      });
      if (!r.ok) return setError(await message(r, 'ذخیره ناموفق بود'));
      apply(await r.json());
      notify('تنظیمات مرکز رویداد ذخیره شد');
    });

  const test = () =>
    act('test', async () => {
      const r = await coreFetch(`${url}/test`, { method: 'POST', headers: J, body: '{}' });
      if (!r.ok) return setError(await message(r, 'ارسال تست ناموفق بود'));
      setResults((await r.json()).results || []);
      await load();
    });

  const inspect = () =>
    act('check', async () => {
      const r = await coreFetch(`${url}/check`, { method: 'POST', headers: J, body: '{}' });
      if (!r.ok) return setError(await message(r, 'بررسی گروه ناموفق بود'));
      setCheck(await r.json());
    });

  const provision = () =>
    act('provision', async () => {
      const r = await coreFetch(`${url}/provision`, { method: 'POST', headers: J, body: '{}' });
      if (!r.ok) return setError(await message(r, 'ساخت Topicها ناموفق بود'));
      const d = await r.json();
      setMade(d.results || []);
      setCheck(null);
      await load();
      if (d.created) notify(`${d.created} Topic ساخته شد`);
    });

  const remove = () => {
    if (!window.confirm('اتصال گروه حذف شود؟ از این پس رویدادی به تلگرام ارسال نمی‌شود.')) return;
    return act('delete', async () => {
      const r = await coreFetch(url, { method: 'DELETE' });
      if (!r.ok) return setError(await message(r, 'حذف ناموفق بود'));
      setResults(null);
      notify('گروه رویدادها حذف شد');
      await load();
    });
  };

  if (data === null) return <Loading rows={3} />;
  const topics = data.topics || [];

  return (
    <div className="space-y-6">
      <section className="card space-y-4">
        <h3 className="flex items-center gap-2 text-base font-extrabold">
          <BellRing size={18} /> مرکز رویداد تلگرام
        </h3>
        <p className="text-sm leading-7 text-muted">
          یک سوپرگروه با قابلیت Topics بسازید و ربات فروشگاه خودتان را ادمین گروه کنید. پرداخت‌ها، سفارش‌ها، بدهی،
          تیکت‌ها و خطاهای فروشگاه شما در Topic مربوطه می‌آید. فقط رویدادهای فروشگاه شما ارسال می‌شود.
        </p>
        {!data.bot_ready && (
          <p className={`${chip} bg-danger-soft text-danger`}>
            <AlertTriangle size={13} /> ابتدا ربات فروشگاه را در «تنظیمات فروشگاه» متصل کنید.
          </p>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block text-xs font-bold text-muted">
            شناسهٔ گروه (Chat ID)
            <input
              className="inp mt-1.5"
              dir="ltr"
              value={chat}
              onChange={(e) => setChat(e.target.value)}
              placeholder="-1001234567890"
            />
          </label>
          <label className="block text-xs font-bold text-muted">
            توضیح (اختیاری)
            <input className="inp mt-1.5" maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
        </div>
        <label className="flex items-center gap-2 text-sm font-bold">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> ارسال رویدادها فعال
          باشد
        </label>
      </section>

      <section className="card space-y-4">
        <h3 className="text-base font-extrabold">Topicها</h3>
        <p className="text-sm text-muted">
          شناسهٔ هر Topic را وارد کنید، یا بعد از ذخیرهٔ گروه «ساخت خودکار Topicها» را بزنید (ربات فروشگاه باید ادمین با
          دسترسی Manage Topics باشد). اگر خالی بماند پیام در General می‌آید.
        </p>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {topics.map((t) => (
            <label key={t.key} className="block text-xs font-bold text-muted">
              {t.label}
              <input
                className="inp mt-1.5"
                dir="ltr"
                inputMode="numeric"
                placeholder="General"
                value={threads[t.key] || ''}
                onChange={(e) => setThreads((x) => ({ ...x, [t.key]: e.target.value }))}
              />
            </label>
          ))}
        </div>
        {error && <p className={`${chip} bg-danger-soft text-danger`}>{error}</p>}
        <div className="flex flex-wrap gap-2">
          <button className="btn" disabled={!chat.trim() || busy !== '' || !data.bot_ready} onClick={save}>
            <BellRing size={15} /> {busy === 'save' ? 'در حال ذخیره…' : 'ذخیره'}
          </button>
          <button className="btn btn-ghost" disabled={!data.configured || busy !== ''} onClick={test}>
            <Send size={15} /> {busy === 'test' ? 'در حال ارسال…' : 'ارسال پیام تست'}
          </button>
          <button className="btn btn-ghost" disabled={!data.configured || busy !== ''} onClick={inspect}>
            <ScanSearch size={15} /> {busy === 'check' ? 'در حال بررسی…' : 'بررسی گروه'}
          </button>
          <button className="btn btn-ghost" disabled={!data.configured || busy !== ''} onClick={provision}>
            <ListPlus size={15} /> {busy === 'provision' ? 'در حال ساخت…' : 'ساخت خودکار Topicها'}
          </button>
          {data.configured && (
            <button className="btn btn-ghost" disabled={busy !== ''} onClick={remove}>
              <Trash2 size={15} /> حذف اتصال
            </button>
          )}
        </div>
      </section>

      {data.configured && (
        <section className="card space-y-3">
          <h3 className="text-base font-extrabold">وضعیت اتصال</h3>
          {data.last_error ? (
            <span className={`${chip} bg-danger-soft text-danger`}>
              <AlertTriangle size={13} /> خطا: {data.last_error} · {fd(data.last_error_at)}
            </span>
          ) : data.last_sent_at ? (
            <span className={`${chip} bg-mint-soft text-mint`}>
              <CheckCircle2 size={13} /> آخرین ارسال موفق: {fd(data.last_sent_at)}
            </span>
          ) : (
            <span className={`${chip} bg-surface2 text-muted`}>هنوز پیامی ارسال نشده</span>
          )}
          {check && (
            <div className="space-y-1 text-sm">
              <div className="font-bold">
                {check.ok ? '✅' : '⚠️'} {check.title || 'گروه'} {check.bot_username ? `· @${check.bot_username}` : ''}
              </div>
              <ul className="list-disc ps-5">
                {check.problems.map((m) => (
                  <li key={m}>{m}</li>
                ))}
              </ul>
              {check.ok && check.missing_topics.length > 0 && (
                <div className="text-muted">
                  برای {check.missing_topics.length} Topic شناسه ثبت نشده؛ «ساخت خودکار Topicها» را بزنید.
                </div>
              )}
            </div>
          )}
          {made && (
            <ul className="space-y-1 text-sm">
              {made.map((x) => (
                <li key={x.topic}>
                  {x.status === 'failed' ? '❌' : x.status === 'created' ? '🆕' : '✔️'} {x.label}
                  {x.status === 'failed' && x.error ? ` — ${x.error}` : ''}
                </li>
              ))}
            </ul>
          )}
          {results && (
            <ul className="space-y-1 text-sm">
              {results.map((x) => (
                <li key={x.topic}>
                  {x.ok ? '✅' : '❌'} {x.label}
                  {!x.ok && x.error ? ` — ${x.error}` : ''}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
