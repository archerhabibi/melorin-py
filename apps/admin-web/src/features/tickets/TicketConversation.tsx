import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, ArrowRight, CheckCheck, CircleDot, Clock, Pencil, RefreshCw, Store, X } from 'lucide-react';
import { confirmDialog, dt } from '../../shared/ui.tsx';
import { Field, errText, useAlive } from '../../shared/kit.tsx';
import { focusOnMount } from '../../shared/useDialog.ts';
import { PRIORITY, DEPARTMENTS, DEPT_LABEL, STATUS_OPTS, dayKey } from './ticketsShared.tsx';
import type { CallFn, Json, Toast } from '../../shared/types.ts';
import { Composer } from './TicketComposer.tsx';
import { Bubble } from './TicketBubble.tsx';

export function Conversation({
  call,
  id,
  toast,
  onChanged,
  onBack,
}: {
  call: CallFn;
  id?: Json;
  toast: Toast;
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
