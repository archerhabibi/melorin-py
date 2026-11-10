import { useEffect, useRef, useState } from 'react';
import { LifeBuoy, ArrowRight, Pencil, Plus, Paperclip, Send, X } from 'lucide-react';
import { Empty, Loading, StatusBadge, fd } from '../ui.jsx';
import { focusOnMount } from '../useDialog.js';
import { J, card, inp } from './DashboardAccounts.jsx';

const PRIO = [
  ['low', 'کم'],
  ['normal', 'عادی'],
  ['high', 'مهم'],
];
const PRIO_LABEL = { low: 'کم', normal: 'عادی', high: 'مهم', urgent: 'فوری' };
const timeOnly = (d) => new Date(d).toLocaleTimeString('fa-IR', { hour: '2-digit', minute: '2-digit' });
const dayLabel = (d) => new Date(d).toLocaleDateString('fa-IR', { dateStyle: 'full' });
export async function msgOf(r, fallback) {
  try {
    const d = await r.json();
    return d?.error?.message || (typeof d?.detail === 'string' ? d.detail : '') || fallback;
  } catch {
    return fallback;
  }
}

const TICKET_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp'];

// Quick check before uploading; the server validates type, size and file signature again and has the last word.
function imageProblem(file) {
  return TICKET_IMAGE_TYPES.includes(file?.type) ? '' : 'فقط تصویر (JPG، PNG یا WebP) مجاز است.';
}

// Step 1 of sending a picture: upload it, get its id back; the id then goes along with the message.
async function uploadTicketImage(coreFetch, path, file) {
  const form = new FormData();
  form.append('file', file);
  const r = await coreFetch(path, { method: 'POST', body: form });
  if (!r.ok) throw new Error(await msgOf(r, 'ارسال تصویر ناموفق بود'));
  return (await r.json()).id;
}

/** Paperclip button that opens the image chooser. */
function AttachButton({ onPick, notify, disabled }) {
  const input = useRef(null);
  return (
    <>
      <input
        ref={input}
        type="file"
        accept={TICKET_IMAGE_TYPES.join(',')}
        className="hidden"
        aria-label="انتخاب تصویر"
        data-testid="ticket-image-input"
        onChange={(e) => {
          const f = e.target.files?.[0] || null;
          e.target.value = '';
          if (!f) return;
          const problem = imageProblem(f);
          if (problem) return notify(problem);
          onPick(f);
        }}
      />
      <button
        type="button"
        disabled={disabled}
        onClick={() => input.current?.click()}
        aria-label="پیوست تصویر"
        title="پیوست تصویر"
        className="grid h-11 w-11 shrink-0 place-items-center rounded-xl border border-line text-muted hover:bg-surface2 disabled:opacity-50"
      >
        <Paperclip size={16} />
      </button>
    </>
  );
}

/** The chosen picture, shown as a removable chip next to the message box. */
function PickedImage({ file, onClear, disabled }) {
  if (!file) return null;
  return (
    <div className="flex items-center gap-2 rounded-xl bg-surface2 px-3 py-2 text-xs">
      <Paperclip size={13} className="shrink-0 text-muted" />
      <span className="latin min-w-0 flex-1 truncate" dir="ltr">
        {file.name}
      </span>
      <button
        type="button"
        disabled={disabled}
        onClick={onClear}
        aria-label="حذف تصویر"
        className="grid h-6 w-6 place-items-center rounded-full text-muted hover:bg-surface"
      >
        <X size={13} />
      </button>
    </div>
  );
}

/** A ticket picture. It needs the login token, so it is fetched and shown from a blob instead of a plain <img src>. */
function TicketImage({ coreFetch, path }) {
  const [src, setSrc] = useState(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let url = null;
    let dead = false;
    setSrc(null);
    setFailed(false);
    coreFetch(path)
      .then((r) => (r.ok ? r.blob() : Promise.reject(new Error('image'))))
      .then((b) => {
        if (dead) return;
        url = URL.createObjectURL(b);
        setSrc(url);
      })
      .catch(() => !dead && setFailed(true));
    return () => {
      dead = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [coreFetch, path]);
  if (failed) return <span className="text-xs text-muted">تصویر بارگذاری نشد</span>;
  if (!src) return <div className="h-32 w-48 animate-pulse rounded-xl bg-surface2" aria-hidden="true" />;
  return (
    <a href={src} target="_blank" rel="noreferrer" aria-label="مشاهدهٔ تصویر در اندازهٔ کامل" className="block">
      <img src={src} alt="تصویر پیوست" className="max-h-64 max-w-full rounded-xl object-contain ring-1 ring-line" />
    </a>
  );
}

function TicketThread({ t, storeId, coreFetch, notify, onBack, onChanged }) {
  const [msgs, setMsgs] = useState(null);
  const [ticket, setTicket] = useState(t);
  const [reply, setReply] = useState('');
  const [pic, setPic] = useState(null); // { file, id } - id is kept once uploaded, so a failed send never uploads twice
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(null); // message id
  const [draft, setDraft] = useState('');
  const [subj, setSubj] = useState(null);
  const end = useRef(null);
  const last = useRef(0);
  const load = () =>
    coreFetch(`/api/v1/tickets/${t.id}/messages`)
      .then((r) => r.json())
      .then((x) => Array.isArray(x) && setMsgs(x))
      .catch(() => {});
  useEffect(() => {
    load();
    const iv = setInterval(() => !document.hidden && load(), 12000);
    return () => clearInterval(iv);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- T-W08: reviewed, dependency list intentionally limited (adding the flagged value risks refetch loops); verify in a browser before changing
  }, [t.id]);
  useEffect(() => {
    const n = msgs?.length || 0;
    if (n !== last.current) {
      end.current?.scrollIntoView({ behavior: last.current ? 'smooth' : 'auto', block: 'end' });
      last.current = n;
    }
  }, [msgs]);
  const me = (m) => !m.is_staff; // customer-side view: only the customer's own messages are editable
  async function patchTicket(body, ok) {
    setBusy(true);
    try {
      const r = await coreFetch(`/api/v1/tickets/${t.id}`, { method: 'PATCH', headers: J, body: JSON.stringify(body) });
      if (!r.ok) return notify(await msgOf(r, 'ذخیره ناموفق بود'));
      setTicket(await r.json());
      onChanged();
      ok && notify(ok);
    } finally {
      setBusy(false);
    }
  }
  async function send() {
    setBusy(true);
    try {
      const payload = { body: reply.trim() };
      if (pic) {
        let id = pic.id;
        if (!id) {
          id = await uploadTicketImage(coreFetch, `/api/v1/stores/${storeId}/tickets/attachments`, pic.file);
          setPic({ file: pic.file, id });
        }
        payload.attachment_id = id;
      }
      const r = await coreFetch(`/api/v1/tickets/${t.id}/messages`, {
        method: 'POST',
        headers: J,
        body: JSON.stringify(payload),
      });
      if (!r.ok) return notify(await msgOf(r, 'ارسال ناموفق بود'));
      setReply('');
      setPic(null);
      setTicket((x) => ({ ...x, status: 'open' }));
      await load();
      onChanged();
    } catch (e) {
      notify(e?.message || 'ارسال ناموفق بود');
    } finally {
      setBusy(false);
    }
  }
  const canSend = !busy && (reply.trim() || pic);
  async function saveEdit(m) {
    setBusy(true);
    try {
      const r = await coreFetch(`/api/v1/tickets/${t.id}/messages/${m.id}`, {
        method: 'PATCH',
        headers: J,
        body: JSON.stringify({ body: draft.trim() }),
      });
      if (!r.ok) return notify(await msgOf(r, 'ویرایش ناموفق بود'));
      setEditing(null);
      await load();
      notify('پیام ویرایش شد');
    } finally {
      setBusy(false);
    }
  }
  const closed = ticket.status === 'closed';
  let prev = '';
  return (
    <div className={`${card} !p-0 flex flex-col overflow-hidden`}>
      <div className="border-b border-line p-4">
        <div className="flex items-start gap-3">
          <button
            onClick={onBack}
            aria-label="بازگشت"
            className="grid h-9 w-9 shrink-0 place-items-center rounded-full ring-1 ring-line hover:bg-surface2"
          >
            <ArrowRight size={16} />
          </button>
          <div className="min-w-0 flex-1">
            {subj === null ? (
              <div className="flex items-center gap-2">
                <h4 className="truncate font-extrabold">{ticket.subject}</h4>
                <button
                  aria-label="ویرایش موضوع"
                  title="ویرایش موضوع"
                  onClick={() => setSubj(ticket.subject)}
                  className="grid h-7 w-7 place-items-center rounded-full text-muted hover:bg-surface2"
                >
                  <Pencil size={13} />
                </button>
              </div>
            ) : (
              <div className="flex gap-2">
                <input
                  ref={focusOnMount}
                  aria-label="موضوع تیکت"
                  className={inp}
                  maxLength={200}
                  value={subj}
                  onChange={(e) => setSubj(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Escape') setSubj(null);
                    if (e.key === 'Enter' && subj.trim().length >= 2) {
                      patchTicket({ subject: subj }, 'موضوع ویرایش شد');
                      setSubj(null);
                    }
                  }}
                />
                <button
                  disabled={subj.trim().length < 2 || busy}
                  className="btn-primary"
                  onClick={() => {
                    patchTicket({ subject: subj }, 'موضوع ویرایش شد');
                    setSubj(null);
                  }}
                >
                  ذخیره
                </button>
              </div>
            )}
            <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-muted">
              <span className="latin font-bold">#{ticket.number}</span>
              <StatusBadge status={ticket.status} />
              <span>اولویت: {PRIO_LABEL[ticket.priority] || 'عادی'}</span>
              <span>· {fd(ticket.created_at)}</span>
            </div>
          </div>
          <button
            disabled={busy}
            onClick={() =>
              patchTicket({ status: closed ? 'open' : 'closed' }, closed ? 'تیکت دوباره باز شد' : 'تیکت بسته شد')
            }
            className="rounded-xl border border-line px-3 py-2 text-xs font-bold hover:bg-surface2 disabled:opacity-50"
          >
            {closed ? 'بازگشایی' : 'بستن تیکت'}
          </button>
        </div>
      </div>
      <div
        className="max-h-[55vh] min-h-[16rem] space-y-4 overflow-y-auto bg-surface2/50 p-4"
        role="log"
        aria-live="polite"
      >
        {msgs === null ? (
          <Loading rows={2} />
        ) : (
          msgs.map((m) => {
            const day = dayLabel(m.created_at);
            const head = day !== prev;
            prev = day;
            return (
              <div key={m.id} className="space-y-3">
                {head && (
                  <div className="flex items-center gap-3 text-[11px] text-muted">
                    <span className="h-px flex-1 bg-line" />
                    {day}
                    <span className="h-px flex-1 bg-line" />
                  </div>
                )}
                <div className={`group flex ${m.is_staff ? 'justify-end' : ''}`}>
                  <div
                    className={`max-w-[88%] rounded-2xl p-3 text-sm leading-7 ${m.is_staff ? 'rounded-tl-sm bg-mint-soft' : 'rounded-tr-sm bg-surface ring-1 ring-line'}`}
                  >
                    <div className="mb-0.5 text-[11px] font-bold text-muted">{m.is_staff ? '🎧 پشتیبانی' : 'شما'}</div>
                    {editing === m.id ? (
                      <div className="space-y-2">
                        <textarea
                          ref={focusOnMount}
                          rows={3}
                          maxLength={10000}
                          dir="auto"
                          className={`${inp} min-w-[min(70vw,24rem)]`}
                          value={draft}
                          onChange={(e) => setDraft(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Escape') setEditing(null);
                            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && draft.trim()) saveEdit(m);
                          }}
                        />
                        <div className="flex gap-2">
                          <button
                            disabled={busy || !draft.trim() || draft.trim() === m.body}
                            onClick={() => saveEdit(m)}
                            className="btn-primary !px-4 !py-2 text-xs"
                          >
                            ذخیرهٔ ویرایش
                          </button>
                          <button
                            onClick={() => setEditing(null)}
                            className="rounded-xl border border-line px-3 text-xs font-bold"
                          >
                            انصراف
                          </button>
                        </div>
                      </div>
                    ) : (
                      <>
                        {m.attachment_id && (
                          <div className={m.body ? 'mb-2' : ''}>
                            <TicketImage
                              coreFetch={coreFetch}
                              path={`/api/v1/tickets/${t.id}/messages/${m.id}/attachment`}
                            />
                          </div>
                        )}
                        {m.body && (
                          <p dir="auto" className="whitespace-pre-wrap break-words">
                            {m.body}
                          </p>
                        )}
                      </>
                    )}
                    <div className="mt-1 flex items-center gap-2 text-[10px] text-muted">
                      <span>{timeOnly(m.created_at)}</span>
                      {m.edited_at && <span className="italic">· ویرایش‌شده</span>}
                      {me(m) && editing !== m.id && !closed && (
                        <button
                          onClick={() => {
                            setEditing(m.id);
                            setDraft(m.body);
                          }}
                          className="mr-auto inline-flex items-center gap-1 font-bold text-coral opacity-0 transition focus-visible:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100"
                        >
                          <Pencil size={11} />
                          ویرایش
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            );
          })
        )}
        {ticket.status === 'answered' && (
          <p className="text-center text-xs text-muted">
            پشتیبانی پاسخ داده است. اگر مشکل ادامه دارد همین‌جا پیام بدهید.
          </p>
        )}
        <div ref={end} />
      </div>
      {closed ? (
        <div className="flex items-center justify-between gap-3 border-t border-line p-4 text-sm">
          <span className="text-muted">این تیکت بسته شده است.</span>
          <button
            disabled={busy}
            onClick={() => patchTicket({ status: 'open' }, 'تیکت دوباره باز شد')}
            className="btn-primary"
          >
            بازگشایی تیکت
          </button>
        </div>
      ) : (
        <div className="space-y-2 border-t border-line p-3">
          <PickedImage file={pic?.file} disabled={busy} onClear={() => setPic(null)} />
          <div className="flex items-end gap-2">
            <AttachButton disabled={busy} notify={notify} onPick={(file) => setPic({ file, id: null })} />
            <textarea
              rows={1}
              dir="auto"
              maxLength={10000}
              aria-label="پیام شما"
              className={`${inp} max-h-40 resize-none`}
              placeholder="پیام خود را بنویسید… (Ctrl+Enter برای ارسال)"
              value={reply}
              onChange={(e) => setReply(e.target.value)}
              onKeyDown={(e) => {
                if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && canSend) send();
              }}
            />
            <button disabled={!canSend} onClick={send} className="btn-primary h-11 shrink-0" aria-label="ارسال">
              <Send size={16} className="-scale-x-100" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function Tickets({ coreFetch, storeId, notify }) {
  const [list, setList] = useState(null);
  const [sel, setSel] = useState(null);
  const [creating, setCreating] = useState(false);
  const [filter, setFilter] = useState('all');
  const [form, setForm] = useState({ subject: '', body: '', priority: 'normal' });
  const [pic, setPic] = useState(null); // { file, id } - see TicketThread
  const [busy, setBusy] = useState(false);
  const load = () =>
    coreFetch(`/api/v1/stores/${storeId}/tickets`)
      .then((r) => r.json())
      .then((x) => setList(Array.isArray(x) ? x : []))
      .catch(() => setList((x) => x || []));
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- T-W08: reviewed, dependency list intentionally limited (adding the flagged value risks refetch loops); verify in a browser before changing
  }, [storeId]);
  async function create() {
    setBusy(true);
    try {
      const payload = { ...form, subject: form.subject.trim(), body: form.body.trim() };
      if (pic) {
        let id = pic.id;
        if (!id) {
          id = await uploadTicketImage(coreFetch, `/api/v1/stores/${storeId}/tickets/attachments`, pic.file);
          setPic({ file: pic.file, id });
        }
        payload.attachment_id = id;
      }
      const r = await coreFetch(`/api/v1/stores/${storeId}/tickets`, {
        method: 'POST',
        headers: J,
        body: JSON.stringify(payload),
      });
      if (!r.ok) return notify(await msgOf(r, 'ثبت تیکت ناموفق بود'));
      const t = await r.json();
      setForm({ subject: '', body: '', priority: 'normal' });
      setPic(null);
      setCreating(false);
      notify(`تیکت #${t.number} ثبت شد`);
      await load();
      setSel(t);
    } catch (e) {
      notify(e?.message || 'ثبت تیکت ناموفق بود');
    } finally {
      setBusy(false);
    }
  }
  if (sel)
    return (
      <TicketThread
        key={sel.id}
        t={sel}
        storeId={storeId}
        coreFetch={coreFetch}
        notify={notify}
        onBack={() => {
          setSel(null);
          load();
        }}
        onChanged={load}
      />
    );
  if (list === null) return <Loading rows={3} />;
  const shown = list.filter(
    (t) => filter === 'all' || (filter === 'closed' ? t.status === 'closed' : t.status !== 'closed'),
  );
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div role="radiogroup" aria-label="فیلتر تیکت‌ها" className="inline-flex gap-1 rounded-xl bg-surface2 p-1">
          {[
            ['all', 'همه'],
            ['active', 'فعال'],
            ['closed', 'بسته'],
          ].map(([v, l]) => (
            <button
              key={v}
              role="radio"
              aria-checked={filter === v}
              onClick={() => setFilter(v)}
              className={`rounded-lg px-3 py-1.5 text-xs font-bold transition ${filter === v ? 'bg-surface text-ink shadow-soft' : 'text-muted'}`}
            >
              {l}
            </button>
          ))}
        </div>
        <button onClick={() => setCreating((x) => !x)} className="btn-primary">
          {creating ? (
            <>
              <X size={16} />
              بستن فرم
            </>
          ) : (
            <>
              <Plus size={16} />
              تیکت جدید
            </>
          )}
        </button>
      </div>
      {creating && (
        <div className={card}>
          <h4 className="font-extrabold">تیکت جدید</h4>
          <div className="mt-3 grid gap-3 sm:grid-cols-[1fr_10rem]">
            <input
              className={inp}
              placeholder="موضوع (مثلاً: اتصال برقرار نمی‌شود)"
              maxLength={200}
              value={form.subject}
              onChange={(e) => setForm({ ...form, subject: e.target.value })}
            />
            <select
              aria-label="اولویت"
              className={inp}
              value={form.priority}
              onChange={(e) => setForm({ ...form, priority: e.target.value })}
            >
              {PRIO.map(([v, l]) => (
                <option key={v} value={v}>
                  اولویت: {l}
                </option>
              ))}
            </select>
          </div>
          <textarea
            rows={5}
            dir="auto"
            maxLength={10000}
            className={`${inp} mt-3`}
            placeholder="توضیحات کامل مشکل یا درخواست…"
            value={form.body}
            onChange={(e) => setForm({ ...form, body: e.target.value })}
          />
          <div className="mt-3 space-y-2">
            <PickedImage file={pic?.file} disabled={busy} onClear={() => setPic(null)} />
            <div className="flex items-center gap-3">
              <AttachButton disabled={busy} notify={notify} onPick={(file) => setPic({ file, id: null })} />
              <span className="min-w-0 flex-1 text-xs text-muted">
                می‌توانید تصویر (اسکرین‌شات یا عکس) هم پیوست کنید. پاسخ پشتیبانی در تلگرام هم به شما اطلاع داده می‌شود.
              </span>
              <button
                disabled={busy || form.subject.trim().length < 2 || !(form.body.trim() || pic)}
                onClick={create}
                className="btn-primary"
              >
                ثبت تیکت
              </button>
            </div>
          </div>
        </div>
      )}
      {shown.length ? (
        <div className="space-y-3">
          {shown.map((t) => (
            <button
              key={t.id}
              onClick={() => setSel(t)}
              className={`${card} flex w-full items-center justify-between gap-3 text-right transition hover:-translate-y-0.5`}
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="latin rounded-md bg-surface2 px-1.5 py-0.5 text-[11px] font-bold text-muted">
                    #{t.number}
                  </span>
                  <b className="truncate">{t.subject}</b>
                </div>
                <div className="mt-1 text-xs text-muted">
                  {fd(t.updated_at)}
                  {t.priority && t.priority !== 'normal' ? ` · اولویت ${PRIO_LABEL[t.priority]}` : ''}
                </div>
              </div>
              <StatusBadge status={t.status} />
            </button>
          ))}
        </div>
      ) : (
        <Empty icon={LifeBuoy} text={list.length ? 'تیکتی با این فیلتر وجود ندارد.' : 'هنوز تیکتی ثبت نکرده‌اید.'}>
          {!list.length && (
            <button onClick={() => setCreating(true)} className="btn-primary mt-5">
              ثبت اولین تیکت
            </button>
          )}
        </Empty>
      )}
    </div>
  );
}
