// Manual tasks: the steps only a human can do outside Melorin when a reseller registers (Google console, BotFather, DNS).
// Core alerts every admin (panel + Telegram) when a task appears; the admin ticks it here once it is done.
import { useState } from 'react';
import { CheckCircle2, ClipboardCopy, Clock, ListChecks, RotateCcw } from 'lucide-react';
import { authFetch } from './api.js';
import { dt } from './ui.jsx';
import { Empty, ErrorBar, KpiBar, Pills, Stat, errText, useRows } from './kit.jsx';

const FILTERS = [
  ['open', 'در انتظار انجام'],
  ['done', 'انجام‌شده'],
  ['all', 'همه'],
];

function TaskCard({ t, busy, onDone, onReopen, toast }) {
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(`${t.title}\n${t.detail}`);
      toast('متن کپی شد');
    } catch {
      /* clipboard blocked: the text is selectable */
    }
  };
  const done = t.status === 'done';
  return (
    <div className={`card p-4 ${done ? 'opacity-70' : ''}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs text-[var(--mu)]">
            {t.store_name ? `${t.store_name} · ` : ''}
            {dt(t.created_at)}
          </div>
          <h4 className="mt-1 text-base font-extrabold">{t.title}</h4>
        </div>
        <span className={`badge ${done ? 'b-ok' : 'b-wn'}`}>{done ? 'انجام شد' : 'در انتظار'}</span>
      </div>
      <p className="mt-3 text-sm leading-7">{t.detail}</p>
      <div className="mt-4 flex flex-wrap gap-2">
        {done ? (
          <button className="btn btn-g" disabled={busy} onClick={() => onReopen(t)}>
            <RotateCcw size={15} /> باز کردن دوباره
          </button>
        ) : (
          <button className="btn" disabled={busy} onClick={() => onDone(t)}>
            <CheckCircle2 size={15} /> انجام دادم
          </button>
        )}
        <button className="btn btn-g" onClick={copy}>
          <ClipboardCopy size={15} /> کپی
        </button>
      </div>
    </div>
  );
}

export default function ManualTasksView({ api, toast }) {
  const call = (p, o = {}) => authFetch(api.base, p, o);
  const { rows, failed, load } = useRows(call, '/api/v1/admin/manual-tasks?status=all');
  const [filter, setFilter] = useState('open');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const all = rows || [];
  const open = all.filter((x) => x.status === 'open').length;
  const shown = all.filter((x) => filter === 'all' || x.status === filter);

  const act = async (t, verb, okMsg) => {
    setBusy(true);
    setError('');
    try {
      const r = await call(`/api/v1/admin/manual-tasks/${t.id}/${verb}`, { method: 'POST', body: '{}' });
      if (!r.ok) setError(await errText(r, 'عملیات ناموفق بود'));
      else {
        toast(okMsg);
        await load();
      }
    } catch {
      setError('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <KpiBar cols={2}>
        <Stat
          label="در انتظار انجام"
          value={open}
          tone="wn"
          Icon={Clock}
          active={filter === 'open'}
          onClick={() => setFilter('open')}
        />
        <Stat
          label="انجام‌شده"
          value={all.length - open}
          tone="ok"
          Icon={CheckCircle2}
          active={filter === 'done'}
          onClick={() => setFilter('done')}
        />
      </KpiBar>
      <Pills
        value={filter}
        onChange={setFilter}
        options={FILTERS.map(([k, l]) => [k, l, k === 'all' ? all.length : all.filter((x) => x.status === k).length])}
      />
      {failed && <ErrorBar onRetry={load}>دریافت فهرست کارهای دستی ناموفق بود.</ErrorBar>}
      {error && <ErrorBar>{error}</ErrorBar>}
      {rows && !shown.length ? (
        <Empty
          Icon={ListChecks}
          title="کار دستی‌ای نیست"
          text="با ثبت‌نام هر نماینده، کارهای دستی گوگل، تلگرام و دامنه اینجا و در تلگرام به شما اطلاع داده می‌شود."
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {shown.map((t) => (
            <TaskCard
              key={t.id}
              t={t}
              busy={busy}
              toast={toast}
              onDone={(x) => act(x, 'done', 'کار انجام‌شده ثبت شد')}
              onReopen={(x) => act(x, 'reopen', 'کار دوباره باز شد')}
            />
          ))}
        </div>
      )}
    </div>
  );
}
