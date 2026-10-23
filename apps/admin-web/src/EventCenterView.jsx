// مرکز رویداد تلگرام: the admin connects ONE Telegram supergroup (with Topics) and maps each event kind to a Topic.
// Core validates everything and does the sending; this screen only edits the settings, shows the connection health and
// sends a real test message to every configured Topic.
import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, BellRing, CheckCircle2, ListPlus, ScanSearch, Send, Trash2 } from 'lucide-react';
import { authFetch } from './api.js';
import { confirmDialog, dt } from './ui.jsx';
import { ErrorBar, Field, Section, digits, errText } from './kit.jsx';

const EMPTY = { configured: false, bot_ready: true, chat_id: '', is_enabled: true, note: '', topics: [] };

export default function EventCenterView({ api, toast }) {
  const call = useCallback((p, o = {}) => authFetch(api.base, p, o), [api.base]);
  const [data, setData] = useState(null);
  const [chat, setChat] = useState('');
  const [threads, setThreads] = useState({});
  const [enabled, setEnabled] = useState(true);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [failed, setFailed] = useState(false);
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
      const r = await call('/api/v1/admin/event-center');
      if (!r.ok) throw 0;
      apply(await r.json());
      setFailed(false);
    } catch {
      setFailed(true);
      setData((x) => x || EMPTY);
    }
  }, [call]);
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
      const topics = Object.fromEntries(Object.entries(threads).map(([k, v]) => [k, digits(v)]));
      const r = await call('/api/v1/admin/event-center', {
        method: 'PUT',
        body: JSON.stringify({ chat_id: chat.trim(), topics, is_enabled: enabled, note: note.trim() || null }),
      });
      if (!r.ok) return setError(await errText(r, 'ذخیره ناموفق بود'));
      apply(await r.json());
      toast('تنظیمات مرکز رویداد ذخیره شد');
    });

  const test = () =>
    act('test', async () => {
      const r = await call('/api/v1/admin/event-center/test', { method: 'POST', body: '{}' });
      if (!r.ok) return setError(await errText(r, 'ارسال تست ناموفق بود'));
      const d = await r.json();
      setResults(d.results || []);
      await load();
    });

  const inspect = () =>
    act('check', async () => {
      const r = await call('/api/v1/admin/event-center/check', { method: 'POST', body: '{}' });
      if (!r.ok) return setError(await errText(r, 'بررسی گروه ناموفق بود'));
      setCheck(await r.json());
    });

  const provision = () =>
    act('provision', async () => {
      const r = await call('/api/v1/admin/event-center/provision', { method: 'POST', body: '{}' });
      if (!r.ok) return setError(await errText(r, 'ساخت Topicها ناموفق بود'));
      const d = await r.json();
      setMade(d.results || []);
      setCheck(null);
      await load();
      if (d.created || d.recreated) {
        toast(
          [d.created && `${d.created} Topic ساخته شد`, d.recreated && `${d.recreated} Topic حذف‌شده دوباره ساخته شد`]
            .filter(Boolean)
            .join('، '),
        );
      }
    });

  const remove = async () => {
    const ok = await confirmDialog('اتصال گروه حذف شود؟ از این پس هیچ رویدادی به تلگرام ارسال نمی‌شود.', {
      title: 'حذف گروه رویدادها',
      ok: 'حذف',
    });
    if (!ok) return;
    await act('delete', async () => {
      const r = await call('/api/v1/admin/event-center', { method: 'DELETE' });
      if (!r.ok) return setError(await errText(r, 'حذف ناموفق بود'));
      setResults(null);
      toast('گروه رویدادها حذف شد');
      await load();
    });
  };

  if (!data) return <div className="card p-6 text-sm text-[var(--mu)]">در حال دریافت…</div>;
  const topics = data.topics || [];
  const canSave = chat.trim() && busy === '';

  return (
    <div className="space-y-5">
      <Section
        title="گروه تلگرام"
        hint="یک سوپرگروه با قابلیت Topics بسازید، ربات اصلی را ادمین کنید (دسترسی ارسال پیام) و شناسهٔ گروه را که با -100 شروع می‌شود وارد کنید."
      >
        {failed && <ErrorBar onRetry={load}>دریافت تنظیمات ناموفق بود.</ErrorBar>}
        {!data.bot_ready && <ErrorBar>ربات اصلی تنظیم نشده است؛ ارسال به گروه ممکن نیست.</ErrorBar>}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="شناسهٔ گروه (Chat ID)" hint="مثال: -1001234567890">
            <input
              className="inp"
              dir="ltr"
              value={chat}
              onChange={(e) => setChat(e.target.value)}
              placeholder="-100…"
            />
          </Field>
          <Field label="توضیح (اختیاری)">
            <input className="inp" maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
        </div>
        <label className="flex items-center gap-2 text-sm font-bold">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> ارسال رویدادها فعال
          باشد
        </label>
      </Section>

      <Section
        title="Topicها"
        hint="شناسهٔ هر Topic را وارد کنید (عدد آخر لینک پیام داخل Topic) یا بعد از ذخیرهٔ گروه، «ساخت خودکار Topicها» را بزنید (ربات باید ادمین با دسترسی Manage Topics باشد). اگر خالی بماند، پیام در General می‌آید."
      >
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {topics.map((t) => (
            <Field key={t.key} label={t.label}>
              <input
                className="inp"
                dir="ltr"
                inputMode="numeric"
                value={threads[t.key] || ''}
                onChange={(e) => setThreads((x) => ({ ...x, [t.key]: e.target.value }))}
                placeholder="General"
              />
            </Field>
          ))}
        </div>
        {error && <ErrorBar>{error}</ErrorBar>}
        <div className="flex flex-wrap items-center gap-2">
          <button className="btn" disabled={!canSave} onClick={save}>
            <BellRing size={15} /> {busy === 'save' ? 'در حال ذخیره…' : 'ذخیره'}
          </button>
          <button className="btn btn-g" disabled={!data.configured || busy !== ''} onClick={test}>
            <Send size={15} /> {busy === 'test' ? 'در حال ارسال…' : 'ارسال پیام تست'}
          </button>
          <button className="btn btn-g" disabled={!data.configured || busy !== ''} onClick={inspect}>
            <ScanSearch size={15} /> {busy === 'check' ? 'در حال بررسی…' : 'بررسی گروه'}
          </button>
          <button className="btn btn-g" disabled={!data.configured || busy !== ''} onClick={provision}>
            <ListPlus size={15} /> {busy === 'provision' ? 'در حال ساخت…' : 'ساخت خودکار Topicها'}
          </button>
          {data.configured && (
            <button className="btn btn-g" disabled={busy !== ''} onClick={remove}>
              <Trash2 size={15} /> حذف اتصال
            </button>
          )}
        </div>
      </Section>

      {data.configured && (
        <Section title="وضعیت اتصال">
          <div className="flex flex-wrap gap-2 text-xs">
            {data.last_error ? (
              <span className="badge b-bd">
                <AlertTriangle size={12} /> خطا: {data.last_error} · {dt(data.last_error_at)}
              </span>
            ) : data.last_sent_at ? (
              <span className="badge b-ok">
                <CheckCircle2 size={12} /> آخرین ارسال موفق: {dt(data.last_sent_at)}
              </span>
            ) : (
              <span className="badge b-mu">هنوز پیامی ارسال نشده</span>
            )}
          </div>
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
                <div className="text-[var(--mu)]">
                  برای {check.missing_topics.length} Topic شناسه ثبت نشده؛ «ساخت خودکار Topicها» را بزنید.
                </div>
              )}
            </div>
          )}
          {made && (
            <ul className="space-y-1 text-sm">
              {made.map((x) => (
                <li key={x.topic}>
                  {x.status === 'failed'
                    ? '❌'
                    : x.status === 'created'
                      ? '🆕'
                      : x.status === 'recreated'
                        ? '♻️'
                        : '✔️'}{' '}
                  {x.label}
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
        </Section>
      )}
    </div>
  );
}
