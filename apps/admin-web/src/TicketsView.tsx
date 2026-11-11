// Ticket desk: inbox + conversation side by side, inline editing, internal notes, quick replies.
import { useCallback, useEffect, useMemo, useState } from 'react';
import { CheckCheck, CircleDot, Inbox, Lock, MessageSquareText, RefreshCw, Search, Zap } from 'lucide-react';
import { Badge } from './ui.tsx';
import { Stat, num, useAlive } from './kit.tsx';

import { fromNow, needsReply, PriorityPill } from './ticketsShared.tsx';
import { Conversation } from './TicketConversation.tsx';
import type { Json, Rec } from './types.ts';

function TicketList({
  rows,
  loading,
  sel,
  onPick,
  q,
  setQ,
  sort,
  setSort,
}: {
  rows?: Json;
  loading?: Json;
  sel?: Json;
  onPick?: Json;
  q?: Json;
  setQ?: Json;
  sort?: Json;
  setSort?: Json;
}) {
  return (
    <div className="card flex min-h-0 flex-col overflow-hidden">
      <div className="space-y-2 border-b border-[var(--ln)] p-3">
        <label className="relative block">
          <Search
            size={15}
            className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[var(--mu)]"
          />
          <input
            aria-label="جستجوی تیکت"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="موضوع، شماره، مشتری…"
            className="inp pr-9"
          />
        </label>
        <div className="flex items-center justify-between text-[11px] text-[var(--mu)]">
          <span>{num(rows.length)} تیکت</span>
          <select
            aria-label="مرتب‌سازی"
            className="rounded-md border border-[var(--ln)] bg-[var(--sf)] px-2 py-1 text-[11px] text-[var(--tx)]"
            value={sort}
            onChange={(e) => setSort(e.target.value)}
          >
            <option value="recent">جدیدترین فعالیت</option>
            <option value="priority">اولویت</option>
            <option value="oldest">قدیمی‌ترین</option>
          </select>
        </div>
      </div>
      <ul className="min-h-0 flex-1 divide-y divide-[var(--ln)] overflow-y-auto" aria-label="فهرست تیکت‌ها">
        {loading ? (
          Array.from({ length: 6 }, (_, i) => (
            <li key={i} className="p-4">
              <div className="skel mb-2 h-4 w-2/3" />
              <div className="skel h-3 w-full" />
            </li>
          ))
        ) : rows.length ? (
          rows.map((t: Json) => {
            const on = sel === t.id;
            const hot = needsReply(t);
            return (
              <li key={t.id}>
                <button
                  onClick={() => onPick(t)}
                  aria-current={on ? 'true' : undefined}
                  className={`relative block w-full p-4 text-right transition ${on ? 'bg-[var(--mb)]' : 'hover:bg-[var(--sf2)]'}`}
                >
                  {on && <span className="absolute inset-y-0 right-0 w-1 bg-[var(--ac)]" />}
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                      {hot && (
                        <span title="منتظر پاسخ شما" className="relative flex h-2 w-2 shrink-0">
                          <span className="pv-ping absolute inline-flex h-full w-full rounded-full bg-[var(--ac)] opacity-70" />
                          <span className="relative h-2 w-2 rounded-full bg-[var(--ac)]" />
                        </span>
                      )}
                      <b className="truncate text-sm">{t.subject}</b>
                    </div>
                    <span className="shrink-0 text-[10px] text-[var(--mu)]">{fromNow(t.updated_at)}</span>
                  </div>
                  <p className="mt-1 truncate text-xs text-[var(--mu)]">
                    {t.last_from_staff ? 'شما: ' : ''}
                    {t.last_message || '—'}
                  </p>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    <span
                      dir="ltr"
                      className="rounded-md bg-[var(--sf2)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--mu)]"
                    >
                      #{t.number || String(t.id).slice(0, 6)}
                    </span>
                    <Badge s={t.status} />
                    <PriorityPill p={t.priority} />
                    <span className="mr-auto inline-flex items-center gap-1 text-[10px] text-[var(--mu)]">
                      <MessageSquareText size={11} />
                      {num(t.message_count)}
                    </span>
                  </div>
                  <div className="mt-1.5 truncate text-[11px] text-[var(--mu)]">
                    {t.customer?.name || t.customer?.email || 'مشتری'}
                  </div>
                </button>
              </li>
            );
          })
        ) : (
          <li className="grid place-items-center p-12 text-center text-sm text-[var(--mu)]">
            <Inbox size={32} className="mb-2 opacity-50" />
            تیکتی با این فیلتر پیدا نشد
          </li>
        )}
      </ul>
    </div>
  );
}

export default function TicketsView({ call, toast }: { call?: Json; toast?: Json }) {
  const [rows, setRows] = useState<Json>(null);
  const [failed, setFailed] = useState(false);
  const [filter, setFilter] = useState('all');
  const [q, setQ] = useState('');
  const [sort, setSort] = useState('recent');
  const [sel, setSel] = useState<Json>(null);
  const alive = useAlive();
  const load = useCallback(async () => {
    try {
      const r = await call('/api/v1/admin/tickets');
      if (!r.ok) throw 0;
      const d = await r.json();
      if (alive.current) {
        setRows(Array.isArray(d) ? d : d.items || []);
        setFailed(false);
      }
    } catch {
      if (alive.current) {
        setFailed(true);
        setRows((x: Json) => x || []);
      }
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    load();
    const iv = setInterval(() => !document.hidden && load(), 20000);
    return () => clearInterval(iv);
  }, [load]);

  // eslint-disable-next-line react-hooks/exhaustive-deps -- T-W08: reviewed, dependency list intentionally limited (adding the flagged value risks refetch loops); verify in a browser before changing
  const all = rows || [];
  const counts = useMemo(
    () => ({
      all: all.length,
      wait: all.filter(needsReply).length,
      answered: all.filter((t: Json) => t.status === 'answered').length,
      closed: all.filter((t: Json) => t.status === 'closed').length,
      urgent: all.filter((t: Json) => t.priority === 'urgent' && t.status !== 'closed').length,
    }),
    [all],
  );
  const shown = useMemo(() => {
    const term = q.trim().toLowerCase();
    let r = all.filter(
      (t: Json) =>
        ({
          all: true,
          wait: needsReply(t),
          answered: t.status === 'answered',
          closed: t.status === 'closed',
          urgent: t.priority === 'urgent' && t.status !== 'closed',
        })[filter],
    );
    if (term)
      r = r.filter((t: Json) =>
        [t.subject, t.number, t.customer?.name, t.customer?.email, t.last_message].some((x) =>
          String(x || '')
            .toLowerCase()
            .includes(term),
        ),
      );
    const rank: Rec = { urgent: 0, high: 1, normal: 2, low: 3 };
    return [...r].sort((a, b) =>
      sort === 'priority'
        ? rank[a.priority] - rank[b.priority] || new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
        : sort === 'oldest'
          ? new Date(a.updated_at).getTime() - new Date(b.updated_at).getTime()
          : new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
    );
  }, [all, filter, q, sort]);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat
          Icon={Inbox}
          tone="in"
          label="همهٔ تیکت‌ها"
          value={counts.all}
          active={filter === 'all'}
          onClick={() => setFilter('all')}
        />
        <Stat
          Icon={CircleDot}
          tone="wn"
          label="منتظر پاسخ"
          value={counts.wait}
          active={filter === 'wait'}
          onClick={() => setFilter('wait')}
        />
        <Stat
          Icon={CheckCheck}
          tone="ok"
          label="پاسخ داده‌شده"
          value={counts.answered}
          active={filter === 'answered'}
          onClick={() => setFilter('answered')}
        />
        <Stat
          Icon={Zap}
          tone="bd"
          label="فوری"
          value={counts.urgent}
          active={filter === 'urgent'}
          onClick={() => setFilter('urgent')}
        />
        <Stat
          Icon={Lock}
          tone="mu"
          label="بسته‌شده"
          value={counts.closed}
          active={filter === 'closed'}
          onClick={() => setFilter('closed')}
        />
      </div>
      {failed && (
        <div
          role="alert"
          className="flex items-center justify-between gap-3 rounded-xl bg-[var(--bdb)] p-3 text-xs text-[var(--bd)]"
        >
          دریافت فهرست تیکت‌ها ناموفق بود.
          <button className="btn btn-g" onClick={load}>
            <RefreshCw size={13} />
            تلاش دوباره
          </button>
        </div>
      )}
      <div className="grid h-[calc(100dvh-17rem)] min-h-[34rem] gap-4 lg:grid-cols-[22rem_minmax(0,1fr)]">
        <div className={`${sel ? 'hidden lg:flex' : 'flex'} min-h-0 flex-col [&>*]:min-h-0 [&>*]:flex-1`}>
          <TicketList
            rows={shown}
            loading={rows === null}
            sel={sel}
            onPick={(t: Json) => setSel(t.id)}
            q={q}
            setQ={setQ}
            sort={sort}
            setSort={setSort}
          />
        </div>
        <div className={`${sel ? 'flex' : 'hidden lg:flex'} min-h-0 flex-col [&>*]:min-h-0 [&>*]:flex-1`}>
          {sel ? (
            <Conversation key={sel} call={call} id={sel} toast={toast} onChanged={load} onBack={() => setSel(null)} />
          ) : (
            <div className="card grid place-items-center p-10 text-center text-[var(--mu)]">
              <div>
                <MessageSquareText size={40} className="mx-auto mb-3 opacity-40" />
                <p className="font-bold text-[var(--tx)]">یک تیکت را انتخاب کنید</p>
                <p className="mt-1 text-xs">گفتگو، ویرایش و پاسخ‌دهی همین‌جا انجام می‌شود.</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
