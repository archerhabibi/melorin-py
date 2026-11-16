import { useEffect, useRef, useState } from 'react';
import { Lock, Pencil } from 'lucide-react';
import { dt } from '../../shared/ui.tsx';
import { focusOnMount } from '../../shared/useDialog.ts';
import { MAX, timeOnly, initials } from './ticketsShared.tsx';
import type { CallFn, Json } from '../../shared/types.ts';

export const IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
// Quick check before uploading; the server validates type, size and file signature again and has the last word.
export const imageProblem = (file: Json) =>
  IMAGE_TYPES.includes(file?.type) ? '' : 'فقط تصویر (JPG، PNG یا WebP) مجاز است.';

/** A ticket picture. It needs the login token, so it is fetched and shown from a blob instead of a plain <img src>. */
export function TicketImage({ call, path }: { call: CallFn; path: string }) {
  const [src, setSrc] = useState<Json>(null);
  const [failed, setFailed] = useState(false);
  const callRef = useRef(call); // `call` is a new function on every render of the page: keep the latest one without refetching
  callRef.current = call;
  useEffect(() => {
    let url: string | null = null;
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
  call: CallFn;
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
