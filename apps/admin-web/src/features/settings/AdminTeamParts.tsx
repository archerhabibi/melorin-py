import { Segmented, errText } from '../../shared/kit.tsx';
import { AREA_LABEL, ROLE_TONE, TEAM_ERRORS } from '../../app/adminAccess.ts';
import { AdminInviteResult, AdminRoleInfo } from '../../shared/types.ts';

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
