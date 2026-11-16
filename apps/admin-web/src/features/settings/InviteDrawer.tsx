import { useState } from 'react';
import { MailPlus, UserPlus } from 'lucide-react';
import { CopyButton, Drawer, Field } from '../../shared/kit.tsx';
import { Facts, useCall } from '../../shared/dataKit.tsx';
import { AdminInviteResult, AdminRoleInfo } from '../../shared/types.ts';
import { BASE, inviteLink, problem, RolePicker } from './AdminTeamParts.tsx';

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
