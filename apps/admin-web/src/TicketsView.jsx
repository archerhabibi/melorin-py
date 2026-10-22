// Ticket desk: inbox + conversation side by side, inline editing, internal notes, quick replies.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  ArrowRight,
  CheckCheck,
  CircleDot,
  Clock,
  Inbox,
  Lock,
  MessageSquareText,
  Pencil,
  RefreshCw,
  Search,
  Send,
  Sparkles,
  Store,
  X,
  Zap,
} from 'lucide-react';
import { Badge, confirmDialog, dt } from './ui.jsx';
import { Field, Segmented, Stat, errText, num, useAlive } from './kit.jsx';

const PRIORITY = { low: ['کم', 'mu'], normal: ['عادی', 'in'], high: ['بالا', 'wn'], urgent: ['فوری', 'bd'] };
const DEPARTMENTS = [
  ['', 'بدون دسته'],
  ['technical', 'فنی'],
  ['billing', 'مالی'],
  ['sales', 'فروش'],
  ['general', 'عمومی'],
];
const DEPT_LABEL = Object.fromEntries(DEPARTMENTS);
const QUICK = [
  ['سلام و احترام', 'سلام، وقت بخیر 🌿\nممنون که با ما در تماس بودید.'],
  ['در حال بررسی', 'درخواست شما در حال بررسی است؛ به‌محض نتیجه، همین‌جا اطلاع می‌دهیم.'],
  ['لطفاً رسید ارسال کنید', 'لطفاً تصویر رسید پرداخت را همراه شمارهٔ پیگیری برای ما ارسال کنید.'],
  [
    'اتصال را بررسی کنید',
    'لطفاً اپلیکیشن را به‌روزرسانی کنید، لینک اشتراک را دوباره وارد کنید و در صورت ادامهٔ مشکل، نوع اینترنت (همراه/ثابت) را اعلام کنید.',
  ],
  ['مشکل برطرف شد', 'مشکل برطرف شد ✅ اگر مورد دیگری بود در خدمتیم. این تیکت بسته می‌شود.'],
];
const MAX = 10000;
const STATUS_OPTS = [
  ['open', 'باز'],
  ['answered', 'پاسخ داده شد'],
  ['closed', 'بسته'],
];

const fromNow = (v) => {
  if (!v) return '';
  const s = (new Date(v).getTime() - Date.now()) / 1000;
  const a = Math.abs(s);
  const rtf = new Intl.RelativeTimeFormat('fa', { numeric: 'auto' });
  if (a < 60) return 'همین الان';
  if (a < 3600) return rtf.format(Math.round(s / 60), 'minute');
  if (a < 86400) return rtf.format(Math.round(s / 3600), 'hour');
  if (a < 86400 * 30) return rtf.format(Math.round(s / 86400), 'day');
  return new Date(v).toLocaleDateString('fa-IR');
};
const dayKey = (v) => new Date(v).toLocaleDateString('fa-IR', { dateStyle: 'full' });
const timeOnly = (v) => new Date(v).toLocaleTimeString('fa-IR', { hour: '2-digit', minute: '2-digit' });
const initials = (s) =>
  String(s || '؟')
    .trim()
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join('') || '؟';
const needsReply = (t) => t.status === 'open' && t.last_from_staff !== true;

function PriorityPill({ p }) {
  const [label, tone] = PRIORITY[p] || PRIORITY.normal;
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-bold"
      style={{ background: `var(--${tone}b, var(--mb))`, color: `var(--${tone}, var(--mu))` }}
    >
      {p === 'urgent' && <Zap size={10} />}
      {label}
    </span>
  );
}

/* ───────────────────────────── list column ───────────────────────────── */
function TicketList({ rows, loading, sel, onPick, q, setQ, sort, setSort }) {
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
          rows.map((t) => {
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

/* ───────────────────────────── conversation ───────────────────────────── */
function Bubble({ m, mine, onEdit, editing, onSaveEdit, onCancelEdit, busy }) {
  const [v, setV] = useState(m.body);
  useEffect(() => setV(m.body), [m.body, editing]);
  const staff = m.is_staff;
  const note = m.is_internal;
  const cls = note
    ? 'border border-dashed border-[var(--wn)] bg-[var(--wnb)]'
    : staff
      ? 'bg-[var(--okb)]'
      : 'bg-[var(--mb)]';
  return (
    <div className={`group flex gap-2 ${staff ? 'flex-row-reverse' : ''}`}>
      <span
        className="mt-1 grid h-8 w-8 shrink-0 place-items-center rounded-full text-[11px] font-extrabold"
        style={{ background: staff ? 'var(--okb)' : 'var(--inb)', color: staff ? 'var(--ok)' : 'var(--in)' }}
      >
        {staff ? 'پ' : initials(m.author_name)}
      </span>
      <div
        className={`max-w-[min(85%,36rem)] rounded-2xl p-3 text-sm leading-7 ${cls} ${staff ? 'rounded-tl-sm' : 'rounded-tr-sm'}`}
      >
        <div className="mb-1 flex flex-wrap items-center gap-x-2 text-[11px] font-bold text-[var(--mu)]">
          {note && (
            <span className="inline-flex items-center gap-1 text-[var(--wn)]">
              <Lock size={11} />
              یادداشت داخلی
            </span>
          )}
          <span>{staff ? m.author_name || 'پشتیبانی' : m.author_name || 'مشتری'}</span>
        </div>
        {editing ? (
          <div className="space-y-2">
            <textarea
              autoFocus
              dir="auto"
              rows={Math.min(10, Math.max(3, v.split('\n').length + 1))}
              maxLength={MAX}
              className="inp min-w-[min(70vw,28rem)]"
              value={v}
              onChange={(e) => setV(e.target.value)}
              onKeyDown={(e) => {
                if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && v.trim()) onSaveEdit(v);
                if (e.key === 'Escape') onCancelEdit();
              }}
            />
            <div className="flex gap-2">
              <button
                disabled={busy || !v.trim() || v.trim() === m.body}
                className="btn !py-1.5"
                onClick={() => onSaveEdit(v)}
              >
                ذخیرهٔ ویرایش
              </button>
              <button className="btn btn-g" onClick={onCancelEdit}>
                انصراف
              </button>
            </div>
          </div>
        ) : (
          <p dir="auto" className="whitespace-pre-wrap break-words">
            {m.body}
          </p>
        )}
        <div className="mt-1.5 flex items-center gap-2 text-[10px] text-[var(--mu)]">
          <time dateTime={m.created_at}>{timeOnly(m.created_at)}</time>
          {m.edited_at && (
            <span title={dt(m.edited_at)} className="italic">
              · ویرایش‌شده
            </span>
          )}
          {mine && !editing && (
            <button
              onClick={onEdit}
              className="mr-auto inline-flex items-center gap-1 rounded-sm px-1 font-bold text-[var(--ac)] opacity-0 transition focus-visible:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100"
            >
              <Pencil size={11} />
              ویرایش
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function Composer({ onSend, busy, ticketStatus }) {
  const [mode, setMode] = useState('reply');
  const [text, setText] = useState('');
  const [quick, setQuick] = useState(false);
  const ta = useRef(null);
  const note = mode === 'note';
  const left = MAX - text.length;
  useEffect(() => {
    const el = ta.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(220, el.scrollHeight)}px`;
  }, [text]);
  const send = async (status) => {
    const ok = await onSend({ body: text.trim(), internal: note, status });
    if (ok) {
      setText('');
      setQuick(false);
    }
  };
  return (
    <div className={`border-t border-[var(--ln)] p-3 ${note ? 'bg-[var(--wnb)]' : 'bg-[var(--sf)]'}`}>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Segmented
          label="نوع پیام"
          value={mode}
          onChange={setMode}
          options={[
            ['reply', 'پاسخ به مشتری'],
            ['note', 'یادداشت داخلی'],
          ]}
        />
        <div className="relative mr-auto">
          <button type="button" className="btn btn-g" aria-expanded={quick} onClick={() => setQuick((x) => !x)}>
            <Sparkles size={13} />
            پاسخ‌های آماده
          </button>
          {quick && (
            <div className="card absolute bottom-full left-0 z-10 mb-2 w-72 overflow-hidden p-1 shadow-xl">
              {QUICK.map(([l, t]) => (
                <button
                  key={l}
                  className="block w-full rounded-lg px-3 py-2 text-right text-xs hover:bg-[var(--mb)]"
                  onClick={() => {
                    setText((x) => (x ? `${x}\n${t}` : t));
                    setQuick(false);
                    ta.current?.focus();
                  }}
                >
                  <b className="block">{l}</b>
                  <span className="line-clamp-1 text-[var(--mu)]">{t}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
      <textarea
        ref={ta}
        dir="auto"
        rows={2}
        maxLength={MAX}
        value={text}
        onChange={(e) => setText(e.target.value)}
        aria-label={note ? 'یادداشت داخلی' : 'پاسخ به مشتری'}
        placeholder={note ? 'فقط برای تیم پشتیبانی دیده می‌شود…' : 'پاسخ خود را بنویسید… (Ctrl+Enter برای ارسال)'}
        className="inp resize-none"
        onKeyDown={(e) => {
          if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && text.trim() && !busy) send();
        }}
      />
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button disabled={busy || !text.trim()} onClick={() => send()} className="btn">
          {note ? (
            <>
              <Lock size={14} />
              ثبت یادداشت
            </>
          ) : (
            <>
              <Send size={14} className="-scale-x-100" />
              ارسال پاسخ
            </>
          )}
        </button>
        {!note && ticketStatus !== 'closed' && (
          <button disabled={busy || !text.trim()} onClick={() => send('closed')} className="btn btn-g">
            <CheckCheck size={14} />
            ارسال و بستن
          </button>
        )}
        <span className={`mr-auto text-[11px] ${left < 200 ? 'text-[var(--bd)]' : 'text-[var(--mu)]'}`}>
          {note ? 'مشتری اطلاع‌رسانی نمی‌شود' : 'مشتری در تلگرام اطلاع می‌گیرد'}
          {left < 500 && ` · ${num(left)} نویسه`}
        </span>
      </div>
    </div>
  );
}

function Conversation({ call, id, toast, onChanged, onBack }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [editSubject, setEditSubject] = useState(null);
  const [editing, setEditing] = useState(null);
  const alive = useAlive();
  const end = useRef(null);
  const lastCount = useRef(0);
  const load = useCallback(
    async (quiet) => {
      try {
        const r = await call(`/api/v1/admin/tickets/${id}`);
        if (!r.ok) throw 0;
        const j = await r.json();
        if (alive.current) {
          setD(j);
          setErr('');
        }
      } catch {
        if (alive.current && !quiet) setErr('دریافت گفتگو ناموفق بود');
      }
    },
    [id],
  );
  useEffect(() => {
    setD(null);
    setEditing(null);
    setEditSubject(null);
    lastCount.current = 0;
    load();
    const iv = setInterval(() => !document.hidden && load(true), 10000);
    return () => clearInterval(iv);
  }, [load]);
  useEffect(() => {
    const n = d?.messages?.length || 0;
    if (n !== lastCount.current) {
      end.current?.scrollIntoView({ behavior: lastCount.current ? 'smooth' : 'auto', block: 'end' });
      lastCount.current = n;
    }
  }, [d]);

  const patch = async (body, okMsg) => {
    setBusy(true);
    try {
      const r = await call(`/api/v1/admin/tickets/${id}`, { method: 'PATCH', body: JSON.stringify(body) });
      if (!r.ok) return toast(await errText(r, 'ذخیره ناموفق بود'));
      await load(true);
      onChanged();
      okMsg && toast(okMsg);
    } finally {
      setBusy(false);
    }
  };
  const send = async (body) => {
    setBusy(true);
    try {
      const r = await call(`/api/v1/admin/tickets/${id}/messages`, { method: 'POST', body: JSON.stringify(body) });
      if (!r.ok) {
        toast(await errText(r, 'ارسال ناموفق بود'));
        return false;
      }
      await load(true);
      onChanged();
      toast(
        body.internal ? 'یادداشت ثبت شد' : body.status === 'closed' ? 'پاسخ ارسال و تیکت بسته شد' : 'پاسخ ارسال شد',
      );
      return true;
    } finally {
      setBusy(false);
    }
  };
  const saveEdit = async (m, text) => {
    setBusy(true);
    try {
      const r = await call(`/api/v1/admin/tickets/${id}/messages/${m.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ body: text }),
      });
      if (!r.ok) return toast(await errText(r, 'ویرایش ناموفق بود'));
      setEditing(null);
      await load(true);
      toast('پیام ویرایش شد');
    } finally {
      setBusy(false);
    }
  };
  const toggleClose = async () => {
    if (
      d.status !== 'closed' &&
      !(await confirmDialog('تیکت بسته شود؟ مشتری می‌تواند با ارسال پیام جدید آن را دوباره باز کند.', {
        title: 'بستن تیکت',
        ok: 'بستن تیکت',
      }))
    )
      return;
    patch(
      { status: d.status === 'closed' ? 'open' : 'closed' },
      d.status === 'closed' ? 'تیکت دوباره باز شد' : 'تیکت بسته شد',
    );
  };

  if (err && !d)
    return (
      <div className="card grid place-items-center p-10 text-center">
        <AlertTriangle className="mb-2 text-[var(--bd)]" />
        <p className="text-sm">{err}</p>
        <button className="btn btn-g mt-3" onClick={() => load()}>
          <RefreshCw size={13} />
          تلاش دوباره
        </button>
      </div>
    );
  if (!d)
    return (
      <div className="card space-y-4 p-6">
        <div className="skel h-6 w-1/2" />
        <div className="skel h-20 w-3/4" />
        <div className="skel mr-auto h-16 w-2/3" />
      </div>
    );

  let prev = '';
  return (
    <div className="card flex min-h-0 flex-col overflow-hidden">
      <header className="space-y-3 border-b border-[var(--ln)] p-4">
        <div className="flex items-start gap-2">
          <button className="btn btn-g !px-2 lg:hidden" aria-label="بازگشت به فهرست" onClick={onBack}>
            <ArrowRight size={16} />
          </button>
          <div className="min-w-0 flex-1">
            {editSubject === null ? (
              <div className="flex items-center gap-2">
                <h3 className="truncate text-base font-extrabold">{d.subject}</h3>
                <button
                  aria-label="ویرایش موضوع"
                  title="ویرایش موضوع"
                  className="btn btn-g !px-1.5"
                  onClick={() => setEditSubject(d.subject)}
                >
                  <Pencil size={12} />
                </button>
              </div>
            ) : (
              <div className="flex gap-2">
                <input
                  autoFocus
                  className="inp"
                  maxLength={200}
                  value={editSubject}
                  onChange={(e) => setEditSubject(e.target.value)}
                  aria-label="موضوع تیکت"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && editSubject.trim().length >= 2) {
                      patch({ subject: editSubject }, 'موضوع ویرایش شد');
                      setEditSubject(null);
                    }
                    if (e.key === 'Escape') setEditSubject(null);
                  }}
                />
                <button
                  disabled={editSubject.trim().length < 2 || busy}
                  className="btn"
                  onClick={() => {
                    patch({ subject: editSubject }, 'موضوع ویرایش شد');
                    setEditSubject(null);
                  }}
                >
                  ذخیره
                </button>
                <button className="btn btn-g" aria-label="انصراف" onClick={() => setEditSubject(null)}>
                  <X size={14} />
                </button>
              </div>
            )}
            <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-[var(--mu)]">
              <span dir="ltr" className="font-mono">
                #{d.number || String(d.id).slice(0, 6)}
              </span>
              <span>
                {d.customer?.name || 'مشتری'}
                {d.customer?.email && (
                  <>
                    {' '}
                    · <span dir="ltr">{d.customer.email}</span>
                  </>
                )}
              </span>
              {d.store_name && (
                <span className="inline-flex items-center gap-1">
                  <Store size={11} />
                  {d.store_name}
                </span>
              )}
              <span className="inline-flex items-center gap-1">
                <Clock size={11} />
                {dt(d.created_at)}
              </span>
            </p>
          </div>
          <button className={`btn ${d.status === 'closed' ? '' : 'btn-g'}`} disabled={busy} onClick={toggleClose}>
            {d.status === 'closed' ? (
              <>
                <CircleDot size={14} />
                بازگشایی
              </>
            ) : (
              <>
                <CheckCheck size={14} />
                بستن تیکت
              </>
            )}
          </button>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Field label="وضعیت">
            <select
              className="inp"
              value={d.status}
              disabled={busy}
              onChange={(e) => patch({ status: e.target.value }, 'وضعیت به‌روز شد')}
            >
              {STATUS_OPTS.map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </Field>
          <Field label="اولویت">
            <select
              className="inp"
              value={d.priority}
              disabled={busy}
              onChange={(e) => patch({ priority: e.target.value }, 'اولویت به‌روز شد')}
            >
              {Object.entries(PRIORITY).map(([v, [l]]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </Field>
          <Field label="دسته‌بندی">
            <select
              className="inp"
              value={d.department || ''}
              disabled={busy}
              onChange={(e) => patch({ department: e.target.value || null }, 'دسته‌بندی به‌روز شد')}
            >
              {!DEPT_LABEL[d.department || ''] && <option value={d.department}>{d.department}</option>}
              {DEPARTMENTS.map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </Field>
        </div>
      </header>
      <div
        className="min-h-0 flex-1 space-y-4 overflow-y-auto bg-[var(--bg)] p-4"
        role="log"
        aria-live="polite"
        aria-label="گفتگو"
      >
        {d.messages.map((m) => {
          const k = dayKey(m.created_at);
          const head = k !== prev;
          prev = k;
          return (
            <div key={m.id} className="space-y-4">
              {head && (
                <div className="flex items-center gap-3 text-[11px] text-[var(--mu)]">
                  <span className="h-px flex-1 bg-[var(--ln)]" />
                  <span>{k}</span>
                  <span className="h-px flex-1 bg-[var(--ln)]" />
                </div>
              )}
              <Bubble
                m={m}
                mine={!!m.mine}
                busy={busy}
                editing={editing === m.id}
                onEdit={() => setEditing(m.id)}
                onCancelEdit={() => setEditing(null)}
                onSaveEdit={(t) => saveEdit(m, t)}
              />
            </div>
          );
        })}
        {d.status === 'closed' && (
          <div className="rounded-xl border border-dashed border-[var(--ln)] p-3 text-center text-xs text-[var(--mu)]">
            این تیکت بسته است. با ارسال پاسخ، وضعیت آن به «پاسخ داده شد» تغییر می‌کند.
          </div>
        )}
        <div ref={end} />
      </div>
      <Composer onSend={send} busy={busy} ticketStatus={d.status} />
    </div>
  );
}

/* ───────────────────────────── page ───────────────────────────── */
export default function TicketsView({ call, toast }) {
  const [rows, setRows] = useState(null);
  const [failed, setFailed] = useState(false);
  const [filter, setFilter] = useState('all');
  const [q, setQ] = useState('');
  const [sort, setSort] = useState('recent');
  const [sel, setSel] = useState(null);
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
        setRows((x) => x || []);
      }
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    load();
    const iv = setInterval(() => !document.hidden && load(), 20000);
    return () => clearInterval(iv);
  }, [load]);

  const all = rows || [];
  const counts = useMemo(
    () => ({
      all: all.length,
      wait: all.filter(needsReply).length,
      answered: all.filter((t) => t.status === 'answered').length,
      closed: all.filter((t) => t.status === 'closed').length,
      urgent: all.filter((t) => t.priority === 'urgent' && t.status !== 'closed').length,
    }),
    [all],
  );
  const shown = useMemo(() => {
    const term = q.trim().toLowerCase();
    let r = all.filter(
      (t) =>
        ({
          all: true,
          wait: needsReply(t),
          answered: t.status === 'answered',
          closed: t.status === 'closed',
          urgent: t.priority === 'urgent' && t.status !== 'closed',
        })[filter],
    );
    if (term)
      r = r.filter((t) =>
        [t.subject, t.number, t.customer?.name, t.customer?.email, t.last_message].some((x) =>
          String(x || '')
            .toLowerCase()
            .includes(term),
        ),
      );
    const rank = { urgent: 0, high: 1, normal: 2, low: 3 };
    return [...r].sort((a, b) =>
      sort === 'priority'
        ? rank[a.priority] - rank[b.priority] || new Date(b.updated_at) - new Date(a.updated_at)
        : sort === 'oldest'
          ? new Date(a.updated_at) - new Date(b.updated_at)
          : new Date(b.updated_at) - new Date(a.updated_at),
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
            onPick={(t) => setSel(t.id)}
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
