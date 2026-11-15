import { useState } from 'react';
import { Clock, Mail, MailPlus, ShieldOff, UserCheck, UserPlus } from 'lucide-react';
import { CopyButton, Drawer, Field, Segmented, errText } from '../../shared/kit.tsx';
import { Avatar, Facts, useCall } from '../../shared/dataKit.tsx';
import { confirmDialog } from '../../shared/ui.tsx';
import { AREA_LABEL, ROLE_TONE, TEAM_ERRORS } from '../../app/adminAccess.ts';
import { AdminInviteResult, AdminMember, AdminRoleInfo, Toast } from '../../shared/types.ts';

export const BASE = '/api/v1/admin/admins';
export const STATE: Record<string, [string, string]> = {
  active: ['b-ok', 'فعال'],
  invited: ['b-wn', 'در انتظار پذیرش دعوت'],
  invite_expired: ['b-bd', 'دعوت منقضی شد'],
  suspended: ['b-mu', 'معلق'],
};

export const RoleBadge = ({ role, label }: { role?: string | null; label?: string | null }) => (
  <span className={`badge b-${ROLE_TONE[role || ''] || 'mu'}`}>{label || 'بدون نقش'}</span>
);
export const StateBadge = ({ state }: { state: string }) => (
  <span className={`badge ${STATE[state]?.[0] || 'b-mu'}`}>{STATE[state]?.[1] || state}</span>
);

/** Absolute link of an invite: the server knows the admin domain, otherwise the browser's own address is the admin address. */
export const inviteLink = (r: AdminInviteResult) => r.invite_url || `${window.location.origin}${r.invite_path}`;

export async function problem(r: Response, fallback: string) {
  const copy = r.clone();
  const code = await copy
    .json()
    .then((d: { error?: { code?: string } }) => d?.error?.code)
    .catch(() => undefined);
  return (code && TEAM_ERRORS[code]) || (await errText(r, fallback));
}

// ───── the permission matrix, shown to whoever picks a role ─────
export function RoleGuide({ roles, value }: { roles: AdminRoleInfo[]; value?: string }) {
  const areas = Object.keys(AREA_LABEL);
  return (
    <div className="overflow-x-auto rounded-xl border border-[var(--ln)] bg-[var(--sf)]">
      <table className="w-full text-xs">
        <caption className="sr-only">ماتریس دسترسی نقش‌ها</caption>
        <thead>
          <tr className="border-b border-[var(--ln)] text-[var(--mu)]">
            <th scope="col" className="px-3 py-2 text-right font-bold">
              بخش
            </th>
            {roles.map((r) => (
              <th
                key={r.key}
                scope="col"
                className={`px-3 py-2 text-center font-bold ${r.key === value ? 'text-[var(--ac)]' : ''}`}
              >
                {r.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {areas.map((a) => (
            <tr key={a} className="border-b border-[var(--ln)] last:border-0">
              <th scope="row" className="px-3 py-2 text-right font-normal">
                {AREA_LABEL[a]}
              </th>
              {roles.map((r) => {
                const p = (r.permissions as string[]).find((x) => x.startsWith(`${a}:`));
                return (
                  <td key={r.key} className={`px-3 py-2 text-center ${r.key === value ? 'bg-[var(--mb)]' : ''}`}>
                    {p?.endsWith(':rw') ? (
                      <span className="font-extrabold text-[var(--ok)]" title="مشاهده و ویرایش">
                        ویرایش
                      </span>
                    ) : p ? (
                      <span className="text-[var(--wn)]" title="فقط مشاهده">
                        مشاهده
                      </span>
                    ) : (
                      <span className="text-[var(--mu)]" aria-label="بدون دسترسی">
                        —
                      </span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function RolePicker({
  roles,
  value,
  onChange,
}: {
  roles: AdminRoleInfo[];
  value: string;
  onChange: (v: string) => void;
}) {
  const current = roles.find((r) => r.key === value);
  return (
    <div className="space-y-3">
      <Segmented value={value} onChange={onChange} label="نقش" options={roles.map((r) => [r.key, r.label])} />
      {current && <p className="text-xs leading-6 text-[var(--mu)]">{current.description}</p>}
      <details className="text-xs">
        <summary className="cursor-pointer font-bold text-[var(--ac)]">مقایسه‌ی کامل نقش‌ها</summary>
        <div className="mt-2">
          <RoleGuide roles={roles} value={value} />
        </div>
      </details>
    </div>
  );
}

// ───── invite drawer ─────
export function InviteDrawer({
  call,
  roles,
  onClose,
  onDone,
}: {
  call: ReturnType<typeof useCall>;
  roles: AdminRoleInfo[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [f, setF] = useState({ email: '', name: '', role: 'support' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [sent, setSent] = useState<AdminInviteResult | null>(null);
  const valid = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(f.email.trim());

  const submit = async () => {
    setBusy(true);
    setError('');
    try {
      const r = await call(BASE, {
        method: 'POST',
        body: JSON.stringify({ email: f.email.trim(), display_name: f.name.trim() || null, role: f.role }),
      });
      if (!r.ok) return setError(await problem(r, 'ارسال دعوت ناموفق بود'));
      setSent((await r.json()) as AdminInviteResult);
      onDone();
    } catch {
      setError('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy(false);
    }
  };

  if (sent) {
    const link = inviteLink(sent);
    return (
      <Drawer
        title="دعوت ساخته شد"
        subtitle={sent.admin.email}
        icon={<MailPlus size={20} className="text-[var(--ok)]" />}
        onClose={onClose}
        footer={
          <button className="btn !py-2 !text-sm" onClick={onClose}>
            تمام
          </button>
        }
      >
        <div className="rounded-xl bg-[var(--okb)] p-4 text-sm leading-7 text-[var(--ok)]">
          {sent.emailed
            ? 'لینک دعوت به ایمیل او فرستاده شد. برای اطمینان می‌توانید همین لینک را هم خودتان برایش بفرستید.'
            : 'ایمیل ارسال نشد (سرویس ایمیل تنظیم نیست یا خطا داد). لینک زیر را خودتان برای او بفرستید.'}
        </div>
        <Field
          label="لینک یک‌بارمصرف دعوت"
          hint="این لینک فقط همین یک بار نمایش داده می‌شود؛ اگر گم شد، دعوت تازه بسازید."
        >
          <div className="flex items-center gap-2">
            <input
              readOnly
              dir="ltr"
              className="inp flex-1 text-xs"
              value={link}
              onFocus={(e) => e.currentTarget.select()}
            />
            <CopyButton text={link} label="کپی لینک دعوت" />
          </div>
        </Field>
        <Facts
          items={[
            { label: 'نقش', value: sent.admin.role_label },
            { label: 'اعتبار لینک تا', value: new Date(sent.expires_at).toLocaleString('fa-IR') },
          ]}
        />
        <p className="text-xs leading-6 text-[var(--mu)]">
          او خودش رمز عبور را می‌سازد و کد احراز هویت (TOTP) را روی گوشی خودش فعال می‌کند. شما هرگز رمز یا کد او را
          نمی‌بینید.
        </p>
      </Drawer>
    );
  }

  return (
    <Drawer
      title="دعوت ادمین جدید"
      subtitle="او با لینک یک‌بارمصرف رمز و ورود دومرحله‌ای خودش را می‌سازد"
      icon={<UserPlus size={20} className="text-[var(--ac)]" />}
      dirty={Boolean(f.email || f.name)}
      busy={busy}
      error={error}
      onClose={onClose}
      footer={
        <button className="btn !py-2 !text-sm" disabled={busy || !valid} onClick={submit}>
          {busy ? 'در حال ارسال…' : 'ساخت و ارسال دعوت'}
        </button>
      }
    >
      <Field label="ایمیل">
        <input
          dir="ltr"
          type="email"
          autoComplete="off"
          className="inp"
          placeholder="name@example.com"
          value={f.email}
          onChange={(e) => setF({ ...f, email: e.target.value })}
        />
      </Field>
      <Field label="نام نمایشی (اختیاری)">
        <input className="inp" maxLength={200} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
      </Field>
      <div>
        <div className="mb-2 text-xs font-bold text-[var(--mu)]">نقش</div>
        <RolePicker roles={roles} value={f.role} onChange={(role) => setF({ ...f, role })} />
      </div>
    </Drawer>
  );
}

// ───── detail drawer ─────
export function AdminDrawer({
  call,
  admin,
  roles,
  toast,
  onClose,
  onChanged,
}: {
  call: ReturnType<typeof useCall>;
  admin: AdminMember;
  roles: AdminRoleInfo[];
  toast: Toast;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [name, setName] = useState<string>(admin.display_name || '');
  const [role, setRole] = useState<string>(admin.role || 'viewer');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [fresh, setFresh] = useState<AdminInviteResult | null>(null);
  const dirty = name !== (admin.display_name || '') || role !== admin.role;
  const settled = admin.state === 'active' || admin.state === 'suspended';

  const run = async (path: string, init: RequestInit, done: string, after?: (r: Response) => Promise<void> | void) => {
    setBusy(true);
    setError('');
    try {
      const r = await call(path, init);
      if (!r.ok) return setError(await problem(r, 'عملیات ناموفق بود'));
      await after?.(r);
      toast(done);
      onChanged();
    } catch {
      setError('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy(false);
    }
  };

  const save = () =>
    run(
      `${BASE}/${admin.id}`,
      { method: 'PATCH', body: JSON.stringify({ display_name: name, role }) },
      'تغییرات ذخیره شد',
      onClose,
    );

  const confirmRun = async (
    message: string,
    opts: { title: string; ok: string; danger?: boolean },
    path: string,
    init: RequestInit,
    done: string,
    after?: (r: Response) => Promise<void> | void,
  ) => {
    if (await confirmDialog(message, opts)) await run(path, init, done, after);
  };

  const toggle = () =>
    admin.state === 'suspended'
      ? run(
          `${BASE}/${admin.id}`,
          { method: 'PATCH', body: JSON.stringify({ is_active: true }) },
          'دسترسی دوباره فعال شد',
          onClose,
        )
      : confirmRun(
          `${admin.display_name || admin.email} تعلیق شود؟ همه‌ی نشست‌های او همین حالا بسته می‌شود.`,
          { title: 'تعلیق ادمین', ok: 'تعلیق', danger: true },
          `${BASE}/${admin.id}`,
          { method: 'PATCH', body: JSON.stringify({ is_active: false }) },
          'ادمین معلق شد',
          onClose,
        );

  const reset = () =>
    confirmRun(
      'رمز عبور و کد احراز هویت این ادمین پاک می‌شود، همه‌ی نشست‌هایش بسته می‌شود و لینک دعوت تازه‌ای ساخته می‌شود. ادامه می‌دهید؟',
      { title: 'بازنشانی دسترسی', ok: 'بازنشانی', danger: true },
      `${BASE}/${admin.id}/reset-access`,
      { method: 'POST', body: '{}' },
      'لینک دعوت تازه ساخته شد',
      async (r) => setFresh((await r.json()) as AdminInviteResult),
    );

  const signOutEverywhere = () =>
    confirmRun(
      'این ادمین از همه‌ی دستگاه‌ها خارج می‌شود (رمز و TOTP او تغییری نمی‌کند).',
      { title: 'خروج از همه‌ی دستگاه‌ها', ok: 'خروج' },
      `${BASE}/${admin.id}/revoke-sessions`,
      { method: 'POST', body: '{}' },
      'نشست‌ها بسته شد',
    );

  const remove = () =>
    confirmRun(
      `${admin.display_name || admin.email} از تیم حذف شود؟ دسترسی‌اش بسته می‌شود؛ سابقه‌ی کارهایش در ممیزی می‌ماند.`,
      { title: 'حذف ادمین', ok: 'حذف', danger: true },
      `${BASE}/${admin.id}`,
      { method: 'DELETE' },
      'ادمین حذف شد',
      onClose,
    );

  if (fresh) {
    const link = inviteLink(fresh);
    return (
      <Drawer
        title="لینک دعوت تازه"
        subtitle={admin.email}
        icon={<Mail size={20} className="text-[var(--ac)]" />}
        onClose={onClose}
        footer={
          <button className="btn !py-2 !text-sm" onClick={onClose}>
            تمام
          </button>
        }
      >
        <p className="text-sm leading-7">
          {fresh.emailed ? 'لینک به ایمیل او هم فرستاده شد.' : 'ایمیل ارسال نشد؛ لینک را خودتان برای او بفرستید.'}{' '}
          دعوت‌های قبلی باطل شدند.
        </p>
        <div className="flex items-center gap-2">
          <input
            readOnly
            dir="ltr"
            className="inp flex-1 text-xs"
            value={link}
            onFocus={(e) => e.currentTarget.select()}
          />
          <CopyButton text={link} label="کپی لینک دعوت" />
        </div>
      </Drawer>
    );
  }

  return (
    <Drawer
      title={admin.display_name || admin.email}
      subtitle={admin.email}
      icon={<Avatar name={admin.display_name || admin.email} tone={ROLE_TONE[admin.role ?? ''] || 'mu'} size={40} />}
      dirty={dirty}
      busy={busy}
      error={error}
      onClose={onClose}
      footer={
        <button className="btn !py-2 !text-sm" disabled={busy || !dirty} onClick={save}>
          {busy ? 'در حال ذخیره…' : 'ذخیره'}
        </button>
      }
    >
      <div className="flex flex-wrap items-center gap-2">
        <StateBadge state={admin.state} />
        <RoleBadge role={admin.role} label={admin.role_label} />
        {admin.is_self && <span className="badge b-in">حساب شما</span>}
        <span className={`badge ${admin.totp_enabled ? 'b-ok' : 'b-wn'}`}>
          {admin.totp_enabled ? 'TOTP فعال' : 'TOTP غیرفعال'}
        </span>
      </div>
      <Facts
        items={[
          {
            label: 'آخرین ورود',
            value: admin.last_login_at ? new Date(admin.last_login_at).toLocaleString('fa-IR') : 'هنوز وارد نشده',
          },
          { label: 'عضو از', value: new Date(admin.created_at).toLocaleDateString('fa-IR') },
          {
            label: 'اعتبار دعوت تا',
            value: admin.invite_expires_at ? new Date(admin.invite_expires_at).toLocaleString('fa-IR') : null,
          },
        ]}
      />
      <Field label="نام نمایشی">
        <input className="inp" maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <div>
        <div className="mb-2 text-xs font-bold text-[var(--mu)]">نقش</div>
        {admin.is_self ? (
          <p className="rounded-xl bg-[var(--mb)] p-3 text-xs leading-6 text-[var(--mu)]">
            نقش حساب خودتان را نمی‌توانید تغییر دهید؛ از مالک دیگری بخواهید.
          </p>
        ) : (
          <RolePicker roles={roles} value={role} onChange={setRole} />
        )}
      </div>

      {!admin.is_self && (
        <section className="space-y-2 rounded-xl border border-[var(--ln)] bg-[var(--sf)] p-4">
          <h3 className="text-sm font-extrabold">امنیت و دسترسی</h3>
          <div className="flex flex-wrap gap-2">
            {settled && (
              <button className="btn btn-g !py-2 !text-xs" disabled={busy} onClick={toggle}>
                {admin.state === 'suspended' ? <UserCheck size={14} /> : <ShieldOff size={14} />}
                {admin.state === 'suspended' ? 'فعال‌سازی دوباره' : 'تعلیق'}
              </button>
            )}
            {admin.state === 'active' && (
              <button className="btn btn-g !py-2 !text-xs" disabled={busy} onClick={signOutEverywhere}>
                <Clock size={14} />
                خروج از همه‌ی دستگاه‌ها
              </button>
            )}
            <button className="btn btn-g !py-2 !text-xs" disabled={busy} onClick={reset}>
              <MailPlus size={14} />
              {admin.state === 'active' || admin.state === 'suspended' ? 'بازنشانی رمز و TOTP' : 'ارسال دوباره‌ی دعوت'}
            </button>
            <button className="btn btn-g !py-2 !text-xs !text-[var(--bd)]" disabled={busy} onClick={remove}>
              حذف از تیم
            </button>
          </div>
          <p className="text-[11px] leading-5 text-[var(--mu)]">
            «بازنشانی» برای گوشی گمشده یا حساب مشکوک است: رمز و TOTP پاک می‌شود و او باید با لینک تازه دوباره راه‌اندازی
            کند.
          </p>
        </section>
      )}
    </Drawer>
  );
}

// ───── the screen ─────
