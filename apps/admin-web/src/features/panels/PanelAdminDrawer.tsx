import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Clock, ExternalLink, KeyRound, Pencil, RefreshCw, UserCog } from 'lucide-react';
import { Badge, confirmDialog, dt } from '../../ui.tsx';
import SubBrandingCard from '../stores/SubBrandingCard.tsx';
import { CopyButton, Drawer, Field, digits } from '../../kit.tsx';
import type { CallFn, Json, Toast } from '../../types.ts';
import { FIELDS, shown, ltr, KindBadge, useCall } from './panelAdminsShared.tsx';

export function AdminDrawer({
  row,
  call,
  toast,
  onClose,
  onDone,
}: {
  row?: Json;
  call: CallFn;
  toast: Toast;
  onClose?: Json;
  onDone?: Json;
}) {
  const { busy, error, run } = useCall(call, toast);
  const init = useMemo(
    () => Object.fromEntries(FIELDS.map(([k]) => [k, row.profile?.[k] == null ? '' : String(row.profile[k])])),
    [row],
  );
  const [form, setForm] = useState(init);
  const [cred, setCred] = useState<Json>(null);
  // an emptied Telegram ID is "unchanged": Core and the panel cannot clear it, so it is never sent
  const changed = FIELDS.map(([k]) => k).filter(
    (k) => form[k].trim() !== init[k] && !(k === 'telegram_id' && !form[k].trim()),
  );
  const set = (k: Json, v: Json) => setForm((f) => ({ ...f, [k]: v }));

  useEffect(() => {
    if (!cred) return undefined;
    const t = setTimeout(() => setCred(null), 60000); // a shown password does not stay on the screen
    return () => clearTimeout(t);
  }, [cred]);

  const save = async () => {
    const profile = Object.fromEntries(changed.map((k) => [k, k === 'telegram_id' ? Number(form[k]) : form[k].trim()]));
    const d = await run('/api/v1/admin/panel-admins/profile', 'PATCH', {
      store_id: row.store_id,
      panel_id: row.panel_id,
      profile,
    });
    if (!d) return;
    const bad = (d.results || []).find((x: Json) => !x.synced);
    toast(
      bad
        ? `ذخیره شد، ولی هنوز روی پنل اعمال نشده؛ تلاش خودکار ادامه دارد${bad.error ? ` (${bad.error})` : ''}`
        : 'پروفایل ذخیره و روی پنل اعمال شد',
    );
    onDone();
  };
  const reveal = async () => {
    if (
      !(await confirmDialog('رمز این ادمین نمایش داده می‌شود و این دسترسی در ممیزی ثبت می‌گردد.', {
        title: 'نمایش اطلاعات ورود',
        ok: 'نمایش',
      }))
    )
      return;
    const d = await run(`/api/v1/admin/panel-admins/${row.id}/credentials`, 'GET');
    if (d) setCred(d);
  };
  const reset = async () => {
    if (
      !(await confirmDialog(`رمز «${row.username}» روی پنل عوض می‌شود و رمز قبلی از کار می‌افتد.`, {
        title: 'ساخت رمز جدید',
        danger: true,
        ok: 'ساخت رمز جدید',
      }))
    )
      return;
    const d = await run(`/api/v1/admin/panel-admins/${row.id}/reset-password`, 'POST', {}, 'رمز جدید ساخته شد');
    if (d) setCred({ ...(cred || {}), username: d.username, password: d.password, panel_url: cred?.panel_url });
  };

  return (
    <Drawer
      title={row.username}
      subtitle={`${row.store_name || '—'} · ${row.panel_name || '—'}`}
      icon={
        <span className="tile h-10 w-10 bg-[var(--inb)] text-[var(--in)]">
          <UserCog size={19} />
        </span>
      }
      dirty={changed.length > 0}
      busy={busy}
      error={error}
      onClose={onClose}
      footer={
        <button className="btn !py-2 !text-sm" disabled={busy || changed.length === 0} onClick={save}>
          <Pencil size={15} />
          ذخیرهٔ پروفایل
        </button>
      }
    >
      <section className="card p-4">
        <h4 className="mb-1 text-[13px] font-extrabold">وضعیت</h4>
        {[
          [
            'فروشگاه',
            <span key="s" className="inline-flex items-center gap-2">
              {row.store_name}
              <KindBadge kind={row.store_kind} />
            </span>,
          ],
          ['پنل', row.panel_name],
          [
            'نام کاربری',
            <span key="u" className="inline-flex items-center gap-1.5">
              {ltr(row.username)}
              <CopyButton text={row.username} label="کپی نام کاربری" />
            </span>,
          ],
          ['نقش', ltr(row.role)],
          ['وضعیت', <Badge key="b" s={row.status} />],
          ['آخرین همگام‌سازی', dt(row.synced_at)],
          ['اکانت‌های قبلی منتقل شد', row.adopted ? 'بله' : 'هنوز نه'],
        ].map(([k, v]) => (
          <div
            key={k}
            className="flex items-start justify-between gap-4 border-b border-[var(--ln)] py-2.5 text-sm last:border-0"
          >
            <span className="shrink-0 text-[var(--mu)]">{k}</span>
            <span className="min-w-0 break-words text-left font-bold">{v ?? '—'}</span>
          </div>
        ))}
        {row.last_error && (
          <p className="mt-3 flex items-start gap-2 rounded-xl bg-[var(--bdb)] p-3 text-xs leading-6 text-[var(--bd)]">
            <AlertTriangle size={15} className="mt-0.5 shrink-0" />
            <span dir="auto" className="break-all">
              {row.last_error}
            </span>
          </p>
        )}
        {!row.profile_synced && (
          <p className="mt-3 flex items-start gap-2 rounded-xl bg-[var(--wnb)] p-3 text-xs leading-6 text-[var(--wn)]">
            <Clock size={15} className="mt-0.5 shrink-0" />
            آخرین ویرایش پروفایل هنوز روی پنل اعمال نشده؛ همگام‌سازی خودکار هر یک دقیقه دوباره تلاش می‌کند.
          </p>
        )}
      </section>

      <section className="card space-y-4 p-4">
        <div>
          <h4 className="text-[13px] font-extrabold">پروفایل و راه‌های تماس</h4>
          <p className="mt-1 text-xs leading-6 text-[var(--mu)]">
            اختیاری است و فقط شما آن را ویرایش می‌کنید. فقط موارد تغییرکرده به پنل فرستاده می‌شود.
          </p>
        </div>
        {FIELDS.map(([k, label, hint, adminOnly]) => (
          <Field key={k} label={adminOnly ? `${label} (فقط ادمین)` : label} hint={hint}>
            {k === 'note' ? (
              <textarea
                rows={2}
                className="inp"
                maxLength={500}
                value={form[k]}
                onChange={(e) => set(k, e.target.value)}
              />
            ) : (
              <input
                className="inp"
                dir={k === 'profile_title' ? 'auto' : 'ltr'}
                inputMode={k === 'telegram_id' ? 'numeric' : undefined}
                maxLength={k === 'profile_title' ? 128 : 512}
                value={form[k]}
                onChange={(e) => set(k, k === 'telegram_id' ? digits(e.target.value) : e.target.value)}
              />
            )}
          </Field>
        ))}
      </section>

      <section className="card space-y-3 p-4">
        <div>
          <h4 className="text-[13px] font-extrabold">اطلاعات ورود به داشبورد PasarGuard</h4>
          <p className="mt-1 text-xs leading-6 text-[var(--mu)]">
            هر نمایش رمز در ممیزی ثبت می‌شود و پس از ۶۰ ثانیه پنهان می‌گردد.
          </p>
        </div>
        {cred ? (
          <div className="space-y-2 rounded-xl bg-[var(--mb)] p-3 text-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[var(--mu)]">نام کاربری</span>
              <span className="inline-flex items-center gap-1.5">
                {ltr(cred.username)}
                <CopyButton text={cred.username} label="کپی نام کاربری" />
              </span>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-[var(--mu)]">رمز</span>
              <span className="inline-flex items-center gap-1.5">
                <code
                  dir="ltr"
                  data-testid="admin-password"
                  className="latin rounded bg-[var(--sf)] px-2 py-1 text-xs font-bold"
                >
                  {cred.password}
                </code>
                <CopyButton text={cred.password} label="کپی رمز" />
              </span>
            </div>
            {cred.panel_url && (
              <a
                dir="ltr"
                className="latin inline-flex items-center gap-1.5 text-xs text-[var(--in)] underline"
                href={cred.panel_url}
                target="_blank"
                rel="noopener noreferrer"
              >
                <ExternalLink size={13} />
                {cred.panel_url}
              </a>
            )}
          </div>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <button className="btn btn-g !py-2 !text-sm" disabled={busy} onClick={reveal}>
            <KeyRound size={15} />
            نمایش رمز
          </button>
          <button className="btn btn-g btn-d !py-2 !text-sm" disabled={busy || row.status !== 'active'} onClick={reset}>
            <RefreshCw size={15} />
            ساخت رمز جدید
          </button>
        </div>
      </section>

      {row.store_id && row.panel_id && row.status === 'active' && (
        <SubBrandingCard
          storeId={row.store_id}
          panelId={row.panel_id}
          panelName={row.panel_name}
          call={call}
          toast={toast}
        />
      )}
    </Drawer>
  );
}
