// "My account": every admin, whatever the role, sees who they are, what the role allows and can change their own password.
// Data: GET /api/v1/admin/me (the same call App uses to filter the menu).
import type { ReactNode } from 'react';
import { ShieldCheck } from 'lucide-react';
import { Facts } from './dataKit.tsx';
import { AREA_LABEL, ROLE_TONE } from './adminAccess.ts';
import type { AdminMe } from './types.ts';

export default function MyAccountView({ me, children }: { me: AdminMe | null | undefined; children?: ReactNode }) {
  const perms: string[] = me?.permissions || [];
  const level = (area: string) => perms.find((p) => p.startsWith(`${area}:`))?.split(':')[1];
  return (
    <div className="space-y-5">
      <section className="card rise p-5">
        <div className="flex flex-wrap items-center gap-3">
          <span className="tile h-12 w-12" style={{ background: 'var(--inb)', color: 'var(--in)' }}>
            <ShieldCheck size={22} />
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-xl font-extrabold">{me?.display_name || me?.email || 'حساب من'}</h2>
            <p dir="ltr" className="truncate text-right text-xs text-[var(--mu)]">
              {me?.email}
            </p>
          </div>
          {me && <span className={`badge b-${ROLE_TONE[me.role ?? ''] || 'mu'}`}>{me.role_label || 'بدون نقش'}</span>}
        </div>
        <div className="mt-4">
          <Facts
            items={[
              { label: 'نقش', value: me?.role_label },
              {
                label: 'بخش‌های قابل ویرایش',
                value:
                  Object.keys(AREA_LABEL)
                    .filter((a) => level(a) === 'rw')
                    .map((a) => AREA_LABEL[a])
                    .join('، ') || 'هیچ',
              },
              {
                label: 'بخش‌های فقط‌مشاهده',
                value:
                  Object.keys(AREA_LABEL)
                    .filter((a) => level(a) === 'r')
                    .map((a) => AREA_LABEL[a])
                    .join('، ') || null,
              },
            ]}
          />
        </div>
        <p className="mt-3 text-xs leading-6 text-[var(--mu)]">
          برای تغییر نقش یا دسترسی با مالک پنل صحبت کنید. اگر گوشی احراز هویت‌تان گم شد، مالک می‌تواند دسترسی شما را
          بازنشانی کند.
        </p>
      </section>
      {children}
    </div>
  );
}
