// Ticket desk: inbox + conversation side by side, inline editing, internal notes, quick replies.
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  ArrowRight,
  CheckCheck,
  CircleDot,
  Clock,
  Lock,
  Paperclip,
  Pencil,
  RefreshCw,
  Send,
  Sparkles,
  Store,
  X,
} from 'lucide-react';
import { confirmDialog, dt } from './ui.tsx';
import { Field, Segmented, errText, num, useAlive } from './kit.tsx';
import { focusOnMount } from './useDialog.ts';

import {
  PRIORITY,
  DEPARTMENTS,
  DEPT_LABEL,
  QUICK,
  MAX,
  STATUS_OPTS,
  dayKey,
  timeOnly,
  initials,
} from './ticketsShared.tsx';
import type { Json, Rec } from './types.ts';

export const IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
// Quick check before uploading; the server validates type, size and file signature again and has the last word.
export const imageProblem = (file: Json) =>
  IMAGE_TYPES.includes(file?.type) ? '' : 'فقط تصویر (JPG، PNG یا WebP) مجاز است.';

/** A ticket picture. It needs the login token, so it is fetched and shown from a blob instead of a plain <img src>. */
export function TicketImage({ call, path }: { call?: Json; path?: Json }) {
  const [src, setSrc] = useState<Json>(null);
  const [failed, setFailed] = useState(false);
  const callRef = useRef(call); // `call` is a new function on every render of the page: keep the latest one without refetching
  callRef.current = call;
  useEffect(() => {
    let url: Json = null;
    let dead = false;
    setSrc(null);
    setFailed(false);
    callRef
      .current(path)
      .then((r: Json) => (r.ok ? r.blob() : Promise.reject(new Error('image'))))
      .then((b: Json) => {
        if (dead) return;
        url = URL.createObjectURL(b);
        setSrc(url);
      })
      .catch(() => !dead && setFailed(true));
    return () => {
      dead = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [path]);
  if (failed) return <span className="text-xs text-[var(--mu)]">تصویر بارگذاری نشد</span>;
  if (!src) return <div className="skel h-32 w-48 rounded-xl" aria-hidden="true" />;
  return (
    <a href={src} target="_blank" rel="noreferrer" aria-label="مشاهدهٔ تصویر در اندازهٔ کامل" className="block">
      <img
        src={src}
        alt="تصویر پیوست"
        className="max-h-64 max-w-full rounded-xl object-contain ring-1 ring-[var(--ln)]"
      />
    </a>
  );
}

/* ───────────────────────────── conversation ───────────────────────────── */
export function Bubble({
  m,
  ticketId,
  call,
  mine,
  onEdit,
  editing,
  onSaveEdit,
  onCancelEdit,
  busy,
}: {
  m?: Json;
  ticketId?: Json;
  call?: Json;
  mine?: Json;
  onEdit?: Json;
  editing?: Json;
  onSaveEdit?: Json;
  onCancelEdit?: Json;
  busy?: Json;
}) {
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
              ref={focusOnMount}
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
          <>
            {m.attachment_id && (
              <div className={m.body ? 'mb-2' : ''}>
                <TicketImage call={call} path={`/api/v1/admin/tickets/${ticketId}/messages/${m.id}/attachment`} />
              </div>
            )}
            {m.body && (
              <p dir="auto" className="whitespace-pre-wrap break-words">
                {m.body}
              </p>
            )}
          </>
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

export function Composer({
  onSend,
  onUpload,
  busy,
  ticketStatus,
  toast,
}: {
  onSend?: Json;
  onUpload?: Json;
  busy?: Json;
  ticketStatus?: Json;
  toast?: Json;
}) {
  const [mode, setMode] = useState('reply');
  const [text, setText] = useState('');
  const [pic, setPic] = useState<Json>(null); // { file, id } - id is kept once uploaded, so a failed send never uploads twice
  const [quick, setQuick] = useState(false);
  const ta = useRef<Json>(null);
  const picker = useRef<Json>(null);
  const note = mode === 'note';
  const left = MAX - text.length;
  useEffect(() => {
    const el = ta.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(220, el.scrollHeight)}px`;
  }, [text]);
  const ready = !!(text.trim() || pic);
  const send = async (status?: Json) => {
    const payload: Rec = { body: text.trim(), internal: note, status };
    if (pic) {
      let id = pic.id;
      if (!id) {
        id = await onUpload(pic.file);
        if (!id) return; // the upload failed and was reported
        setPic({ file: pic.file, id });
      }
      payload.attachment_id = id;
    }
    const ok = await onSend(payload);
    if (ok) {
      setText('');
      setPic(null);
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
      {pic && (
        <div className="mb-2 flex items-center gap-2 rounded-xl bg-[var(--mb)] px-3 py-2 text-xs">
          <Paperclip size={13} className="shrink-0 text-[var(--mu)]" />
          <span dir="ltr" className="min-w-0 flex-1 truncate font-mono">
            {pic.file.name}
          </span>
          <button
            type="button"
            disabled={busy}
            aria-label="حذف تصویر"
            className="btn btn-g !px-1.5 !py-1"
            onClick={() => setPic(null)}
          >
            <X size={12} />
          </button>
        </div>
      )}
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
          if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && ready && !busy) send();
        }}
      />
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <input
          ref={picker}
          type="file"
          accept={IMAGE_TYPES.join(',')}
          className="hidden"
          aria-label="انتخاب تصویر"
          data-testid="ticket-image-input"
          onChange={(e) => {
            const f = e.target.files?.[0] || null;
            e.target.value = '';
            if (!f) return;
            const problem = imageProblem(f);
            if (problem) return toast(problem);
            setPic({ file: f, id: null });
          }}
        />
        <button
          type="button"
          disabled={busy}
          className="btn btn-g"
          aria-label="پیوست تصویر"
          title="پیوست تصویر"
          onClick={() => picker.current?.click()}
        >
          <Paperclip size={14} />
        </button>
        <button disabled={busy || !ready} onClick={() => send()} className="btn">
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
          <button disabled={busy || !ready} onClick={() => send('closed')} className="btn btn-g">
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

export function Conversation({
  call,
  id,
  toast,
  onChanged,
  onBack,
}: {
  call?: Json;
  id?: Json;
  toast?: Json;
  onChanged?: Json;
  onBack?: Json;
}) {
  const [d, setD] = useState<Json>(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [editSubject, setEditSubject] = useState<Json>(null);
  const [editing, setEditing] = useState<Json>(null);
  const alive = useAlive();
  const end = useRef<Json>(null);
  const lastCount = useRef(0);
  const load = useCallback(
    async (quiet?: boolean) => {
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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- T-W08: reviewed, dependency list intentionally limited (adding the flagged value risks refetch loops); verify in a browser before changing
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

  const patch = async (body: Json, okMsg: Json) => {
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
  const upload = async (file: Json) => {
    setBusy(true);
    try {
      const form = new FormData();
      form.append('file', file);
      const r = await call('/api/v1/admin/tickets/attachments', { method: 'POST', body: form });
      if (!r.ok) {
        toast(await errText(r, 'ارسال تصویر ناموفق بود'));
        return null;
      }
      return (await r.json()).id;
    } catch {
      toast('ارسال تصویر ناموفق بود');
      return null;
    } finally {
      setBusy(false);
    }
  };
  const send = async (body?: Json) => {
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
  const saveEdit = async (m: Json, text: Json) => {
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
                  ref={focusOnMount}
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
        {d.messages.map((m: Json) => {
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
                ticketId={id}
                call={call}
                mine={!!m.mine}
                busy={busy}
                editing={editing === m.id}
                onEdit={() => setEditing(m.id)}
                onCancelEdit={() => setEditing(null)}
                onSaveEdit={(t: Json) => saveEdit(m, t)}
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
      <Composer onSend={send} onUpload={upload} busy={busy} ticketStatus={d.status} toast={toast} />
    </div>
  );
}

/* ───────────────────────────── page ───────────────────────────── */
