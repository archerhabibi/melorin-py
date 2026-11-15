import { useEffect, useRef, useState } from 'react';
import { CheckCheck, Lock, Paperclip, Send, Sparkles, X } from 'lucide-react';
import { Segmented, num } from '../../kit.tsx';
import { QUICK, MAX } from './ticketsShared.tsx';
import { IMAGE_TYPES, imageProblem } from './TicketBubble.tsx';
import type { Json, Rec, Toast } from '../../types.ts';

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
  toast: Toast;
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
