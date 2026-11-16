import { useState } from 'react';
import { CheckCircle2, Inbox, XCircle } from 'lucide-react';
import { Badge, confirmDialog, dt } from '../../shared/ui.tsx';
import { Drawer, Field, digits, num } from '../../shared/kit.tsx';
import type { CallFn, Json, Toast } from '../../shared/types.ts';
import { FIELDS, LABEL, ltr, useCall } from './panelAdminsShared.tsx';

export function RequestDrawer({
  req,
  call,
  toast,
  onClose,
  onDone,
}: {
  req?: Json;
  call: CallFn;
  toast: Toast;
  onClose?: Json;
  onDone?: Json;
}) {
  const { busy, error, setError, run } = useCall(call, toast);
  const pending = req.status === 'pending';
  const keys = FIELDS.map(([k]) => k).filter((k) => k in (req.changes || {}));
  const [on, setOn] = useState(() => Object.fromEntries(keys.map((k) => [k, true])));
  const asked = (k: Json) => (req.changes[k] == null ? '' : String(req.changes[k]));
  const [vals, setVals] = useState(() => Object.fromEntries(keys.map((k) => [k, asked(k)])));
  const [note, setNote] = useState('');
  const edited = keys.some((k) => on[k] && vals[k] !== asked(k));

  const apply = async () => {
    const picked = keys.filter((k) => on[k]);
    if (!picked.length) return setError('حداقل یک مورد را برای اعمال انتخاب کنید.');
    if (picked.includes('telegram_id') && !vals.telegram_id.trim())
      return setError('آیدی تلگرام نمی‌تواند خالی باشد (پاک‌کردن پشتیبانی نمی‌شود).');
    if (
      !(await confirmDialog(
        `${num(picked.length)} مورد روی ادمین پنل «${req.store_name}» اعمال می‌شود${edited ? ' (با ویرایش شما)' : ''}.`,
        {
          title: 'اعمال تغییرات',
          ok: 'اعمال',
        },
      ))
    )
      return;
    const changes = Object.fromEntries(picked.map((k) => [k, k === 'telegram_id' ? Number(vals[k]) : vals[k].trim()]));
    const d = await run(
      `/api/v1/admin/panel-admin-requests/${req.id}/apply`,
      'POST',
      { changes, note: note.trim() || null },
      'تغییرات اعمال شد',
    );
    if (d) onDone();
  };
  const reject = async () => {
    if (
      !(await confirmDialog('درخواست رد می‌شود و توضیح شما برای نماینده ارسال می‌گردد.', {
        title: 'رد درخواست',
        danger: true,
        ok: 'رد درخواست',
      }))
    )
      return;
    const d = await run(
      `/api/v1/admin/panel-admin-requests/${req.id}/reject`,
      'POST',
      { note: note.trim() },
      'درخواست رد شد',
    );
    if (d) onDone();
  };

  return (
    <Drawer
      title={req.store_name || 'درخواست تغییر'}
      subtitle={`درخواست تغییر پروفایل ادمین پنل · ${dt(req.created_at)}`}
      icon={
        <span className="tile h-10 w-10 bg-[var(--inb)] text-[var(--in)]">
          <Inbox size={19} />
        </span>
      }
      dirty={pending && (edited || note.trim().length > 0)}
      busy={busy}
      error={error}
      onClose={onClose}
      footer={
        pending ? (
          <>
            <button className="btn !py-2 !text-sm" disabled={busy} onClick={apply}>
              <CheckCircle2 size={15} />
              اعمال تغییرات
            </button>
            <button
              className="btn btn-g btn-d !py-2 !text-sm"
              disabled={busy || note.trim().length < 3}
              title={note.trim().length < 3 ? 'برای رد، توضیح بنویسید' : undefined}
              onClick={reject}
            >
              <XCircle size={15} />
              رد درخواست
            </button>
          </>
        ) : null
      }
    >
      {req.message && (
        <p className="whitespace-pre-line rounded-xl bg-[var(--mb)] p-3 text-xs leading-6">{req.message}</p>
      )}
      <section className="card p-4">
        <h4 className="mb-2 text-[13px] font-extrabold">
          {pending ? 'تغییرات درخواستی (قابل ویرایش)' : 'تغییرات درخواستی'}
        </h4>
        <div className="space-y-3">
          {keys.map((k) => (
            <div key={k} className="rounded-xl border border-[var(--ln)] p-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="text-xs font-extrabold">{LABEL[k]}</span>
                {pending && (
                  <label className="flex items-center gap-1.5 text-xs text-[var(--mu)]">
                    <input
                      type="checkbox"
                      checked={on[k]}
                      onChange={(e) => setOn((o) => ({ ...o, [k]: e.target.checked }))}
                    />
                    اعمال شود
                  </label>
                )}
              </div>
              <div className="mb-2 text-[11px] text-[var(--mu)]">فعلی: {ltr(req.current_profile?.[k])}</div>
              {pending ? (
                <input
                  className="inp"
                  dir="ltr"
                  aria-label={`مقدار جدید ${LABEL[k]}`}
                  disabled={!on[k]}
                  inputMode={k === 'telegram_id' ? 'numeric' : undefined}
                  value={vals[k]}
                  onChange={(e) =>
                    setVals((v) => ({ ...v, [k]: k === 'telegram_id' ? digits(e.target.value) : e.target.value }))
                  }
                />
              ) : (
                <div className="text-sm font-bold">{ltr(req.changes[k])}</div>
              )}
            </div>
          ))}
        </div>
      </section>
      {pending ? (
        <section className="card p-4">
          <Field
            label="توضیح برای نماینده"
            hint="برای رد الزامی است؛ برای اعمال اختیاری و همراه اعلان به نماینده ارسال می‌شود."
          >
            <textarea rows={3} className="inp" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
        </section>
      ) : (
        <section className="card p-4">
          <h4 className="mb-1 text-[13px] font-extrabold">نتیجه</h4>
          {[
            ['وضعیت', <Badge key="s" s={req.status} />],
            ['زمان بررسی', dt(req.reviewed_at)],
            ['توضیح', req.review_note],
          ].map(([k, v]) => (
            <div
              key={k}
              className="flex items-start justify-between gap-4 border-b border-[var(--ln)] py-2.5 text-sm last:border-0"
            >
              <span className="shrink-0 text-[var(--mu)]">{k}</span>
              <span className="min-w-0 break-words text-left font-bold">{v ?? '—'}</span>
            </div>
          ))}
        </section>
      )}
    </Drawer>
  );
}
