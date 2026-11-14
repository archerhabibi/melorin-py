// مرکز رویداد تلگرام (reseller): the owner connects a Telegram supergroup (with Topics) for HIS store's events only. Messages
// are sent with the store's OWN bot, never the main bot. Core validates and sends; this tab edits settings and shows health.
import { useCallback } from 'react';
import { AlertTriangle, BellRing, CheckCircle2, ListPlus, ScanSearch, Send, Trash2 } from 'lucide-react';
import { useEventCenter } from '@melorin/web-kit/eventCenter.js';
import { Loading, fd } from './ui.tsx';
import type { Json } from './types';

const chip = 'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-bold';

export default function ResellerEventCenter({
  coreFetch,
  base,
  notify,
}: {
  coreFetch?: Json;
  base?: Json;
  notify?: Json;
}) {
  const confirm = useCallback((m: string) => window.confirm(m), []);
  const {
    data,
    chat,
    setChat,
    threads,
    setThreads,
    enabled,
    setEnabled,
    note,
    setNote,
    busy,
    error: err,
    failed,
    results,
    check,
    made,
    save,
    test,
    inspect,
    provision,
    remove,
  } = useEventCenter({ call: coreFetch, url: `${base}/event-center`, notify, confirm });
  const error = err || (failed ? 'دریافت تنظیمات ناموفق بود' : '');

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
          تیکت‌ها، خطاها و اکانت‌های تست فروشگاه شما در Topic مربوطه می‌آید و هر شب ساعت ۰۰:۰۰ (وقت تهران) یک «گزارش
          شبانه» از ۲۴ ساعت گذشته می‌رسد. فقط رویدادهای فروشگاه شما ارسال می‌شود.
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
          {topics.map((t: Json) => (
            <label key={t.key} className="block text-xs font-bold text-muted">
              {t.label}
              <input
                className="inp mt-1.5"
                dir="ltr"
                inputMode="numeric"
                placeholder="General"
                value={threads[t.key] || ''}
                onChange={(e) => setThreads((x: Json) => ({ ...x, [t.key]: e.target.value }))}
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
                {check.problems.map((m: Json) => (
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
              {made.map((x: Json) => (
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
              {results.map((x: Json) => (
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
