import { useState } from 'react';
import { Clock, RotateCcw } from 'lucide-react';
import { typedClient } from '../../api/api.ts';
import { dt } from '../../shared/ui.tsx';
import { Drawer, Field, errText } from '../../shared/kit.tsx';
import type { CallFn, Json, Toast } from '../../shared/types.ts';
import { reasonOf, prov, ProviderTile, StatusBadge, UserCard, Advice } from './IdentityReviewParts';

export function ReviewDrawer({
  r,
  call,
  base,
  toast,
  onClose,
  onDone,
}: {
  r?: Json;
  call: CallFn;
  base: string;
  toast: Toast;
  onClose?: Json;
  onDone?: Json;
}) {
  const [note, setNote] = useState(r.resolution_note || '');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [why, explain] = reasonOf(r.reason);
  const run = async (kind: Json) => {
    setBusy(true);
    setErr('');
    try {
      const params = { path: { review_id: r.id } };
      const { response: res } =
        kind === 'dismiss'
          ? await typedClient(base).post('/api/v1/admin/identity-link-reviews/{review_id}/dismiss', {
              params,
              body: { note: note.trim() || null },
            })
          : await typedClient(base).post('/api/v1/admin/identity-link-reviews/{review_id}/reopen', { params });
      if (!res.ok) {
        setErr(await errText(res, 'عملیات ناموفق بود'));
        return;
      }
      toast(kind === 'dismiss' ? 'درخواست رد شد' : 'به صف باز برگشت');
      onDone();
    } catch {
      setErr('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy(false);
    }
  };
  const open = r.status === 'open';
  return (
    <Drawer
      title="بررسی تعارض هویت"
      subtitle={r.email || 'بدون ایمیل'}
      icon={<ProviderTile p={r.provider} />}
      dirty={open && note.trim() !== (r.resolution_note || '')}
      busy={busy}
      error={err}
      onClose={onClose}
      footer={
        open ? (
          <button className="btn !bg-[var(--bd)] !text-white" disabled={busy} onClick={() => run('dismiss')}>
            رد درخواست
          </button>
        ) : r.status === 'dismissed' ? (
          <button className="btn" disabled={busy} onClick={() => run('reopen')}>
            <RotateCcw size={14} />
            بازگرداندن به صف
          </button>
        ) : null
      }
    >
      <section className="card space-y-3 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge s={r.status} />
          <span className="spec">{prov(r.provider).label}</span>
          <span className="spec">
            <Clock size={12} />
            {dt(r.created_at)}
          </span>
        </div>
        <h3 className="text-sm font-extrabold">{why}</h3>
        <p className="text-xs leading-6 text-[var(--mu)]">{explain}</p>
      </section>
      <Advice r={r} />
      <section className="grid gap-3 sm:grid-cols-2">
        <UserCard u={r.source_user} role="حساب درخواست‌دهنده" fallbackId={r.source_user_id} />
        <div className="grid gap-3">
          {r.candidates?.length ? (
            r.candidates.map((c: Json) => <UserCard key={c.id} u={c} role="حساب موجود" />)
          ) : (
            <UserCard u={null} role="حساب موجود" fallbackId={r.candidate_user_ids?.[0]} />
          )}
        </div>
      </section>
      <section className="card space-y-3 p-4">
        <Field label="یادداشت ادمین" hint="در لاگ ممیزی ثبت می‌شود (حداکثر ۵۰۰ نویسه).">
          <textarea
            className="inp min-h-24"
            maxLength={500}
            disabled={!open}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="مثلاً: با کاربر از طریق تیکت تماس گرفته شد؛ دو حساب متعلق به یک نفر نیست."
          />
        </Field>
        {r.resolved_at && <p className="text-[11px] text-[var(--mu)]">آخرین تغییر: {dt(r.resolved_at)}</p>}
      </section>
    </Drawer>
  );
}
