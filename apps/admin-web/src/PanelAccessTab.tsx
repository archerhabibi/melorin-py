// «دسترسی» tab of the panel detail (PG-12): which credential level Melorin runs on at this panel, the least-privilege service
// admin (provision / rotate / list keys) and the store role new store admins get (plan / apply / revert).
// Reads need nothing. Every write asks the admin to type the panel name; the owner credential is sent once, never kept.
import { useCallback, useEffect, useState } from 'react';
import { Secret } from './kit.tsx';
import { getJson, typedClient } from './api.ts';
import { confirmDialog } from './ui.tsx';
import type { Toast } from './types.ts';
import { errMessage } from './adminHubTypes.ts';

interface Access {
  level: string;
  role?: string | null;
  provisioned?: boolean;
  warnings?: string[];
}
interface RolePlan {
  role: string;
  applied?: boolean;
  grants?: string[];
  withheld?: string[];
}
interface KeyRow {
  id: string | number;
  name: string;
  status: string;
  request_count?: number;
}

export default function PanelAccessTab({
  api,
  panelId,
  panelName,
  toast,
}: {
  api: { base: string };
  panelId?: string;
  panelName?: string;
  toast: Toast;
}) {
  const [access, setAccess] = useState<Access | null>(null);
  const [plan, setPlan] = useState<RolePlan | null>(null);
  const [keys, setKeys] = useState<KeyRow[] | null>(null);
  const [confirm, setConfirm] = useState('');
  const [owner, setOwner] = useState({ api_key: '', username: '', password: '' });
  const [roleName, setRoleName] = useState('');
  const [busy, setBusy] = useState(false);

  const base = `/api/v1/admin/panels/${panelId}`;
  const load = useCallback(async () => {
    if (!panelId) return;
    try {
      const [a, p] = await Promise.all([
        getJson<Access>(api.base, `${base}/service-access`),
        getJson<RolePlan>(api.base, `${base}/store-role-plan`),
      ]);
      setAccess(a);
      setPlan(p);
    } catch {
      toast('دریافت وضعیت دسترسی پنل ناموفق بود');
    }
  }, [api.base, base, panelId, toast]);
  useEffect(() => {
    setAccess(null);
    setPlan(null);
    setKeys(null);
    load();
  }, [load]);

  if (!panelId) return <p className="text-sm text-[var(--mu)]">یک پنل انتخاب کنید.</p>;

  const bootstrap = () => {
    const b = Object.fromEntries(Object.entries(owner).filter(([, v]) => v.trim()));
    return Object.keys(b).length ? b : null;
  };
  const nameOk = !panelName || confirm.trim() === panelName;

  // One literal typed path per write action, so the schema checks every body.
  type Action = '/service-access/provision' | '/service-access/rotate' | '/store-role/apply' | '/store-role/revert';
  const send = (
    path: Action,
    body: { confirm_name: string; bootstrap: ReturnType<typeof bootstrap>; role_name?: string | null },
  ) => {
    const params = { params: { path: { panel_id: String(panelId) } } };
    const c = typedClient(api.base);
    if (path === '/service-access/provision')
      return c.post('/api/v1/admin/panels/{panel_id}/service-access/provision', { ...params, body });
    if (path === '/service-access/rotate')
      return c.post('/api/v1/admin/panels/{panel_id}/service-access/rotate', { ...params, body });
    if (path === '/store-role/apply')
      return c.post('/api/v1/admin/panels/{panel_id}/store-role/apply', { ...params, body });
    return c.post('/api/v1/admin/panels/{panel_id}/store-role/revert', { ...params, body });
  };
  const failText = (error: unknown, status: number) => {
    const d = (error ?? {}) as { error?: { message?: string }; detail?: unknown };
    const det = d.detail as { message?: string; msg?: string }[] | { message?: string } | string | undefined;
    return (
      d.error?.message ||
      (typeof det === 'string'
        ? det
        : Array.isArray(det)
          ? det[0]?.msg?.replace(/^Value error, /, '')
          : det?.message) ||
      String(status)
    );
  };

  const run = async (
    path: Action,
    label: string,
    opts: { danger?: boolean; needsOwner?: boolean; extra?: Record<string, unknown> },
  ) => {
    if (opts.needsOwner && !bootstrap()) {
      toast('برای این کار اعتبارنامه‌ی owner پنل لازم است');
      return;
    }
    if (
      !(await confirmDialog(`${label} روی خود پنل اعمال می‌شود. ادامه می‌دهید؟`, {
        title: label,
        danger: !!opts.danger,
        ok: 'اجرا',
      }))
    )
      return;
    setBusy(true);
    try {
      const { response: r, error } = await send(path, {
        confirm_name: confirm.trim(),
        bootstrap: bootstrap(),
        ...opts.extra,
      });
      if (!r.ok) throw new Error(failText(error, r.status));
      toast(`${label} انجام شد`);
      setOwner({ api_key: '', username: '', password: '' }); // the credential never lingers in the form
      await load();
    } catch (e) {
      toast(`ناموفق: ${errMessage(e)}`);
    }
    setBusy(false);
  };

  const listKeys = async () => {
    if (!bootstrap()) {
      toast('برای فهرست کلیدها اعتبارنامه‌ی owner لازم است');
      return;
    }
    setBusy(true);
    try {
      const {
        response: r,
        data,
        error,
      } = await typedClient(api.base).post('/api/v1/admin/panels/{panel_id}/service-access/keys', {
        params: { path: { panel_id: String(panelId) } },
        body: bootstrap() ?? {},
      });
      if (!r.ok) throw new Error(failText(error, r.status));
      setKeys(((data ?? {}) as { keys?: KeyRow[] }).keys || []);
    } catch (e) {
      toast(`ناموفق: ${errMessage(e)}`);
    }
    setBusy(false);
  };

  return (
    <div className="space-y-4" aria-busy={busy}>
      <section className="card space-y-2 p-4">
        <h3 className="font-extrabold">دسترسی سرویس ملورین</h3>
        {!access ? (
          <div className="skel h-16" />
        ) : (
          <>
            <p className="text-sm">
              سطح دسترسی: <b>{String(access.level)}</b> · نقش: <b>{String(access.role ?? '—')}</b> ·{' '}
              {access.provisioned ? 'ادمین سرویس ساخته شده' : 'هنوز با دسترسی کامل owner کار می‌کند'}
            </p>
            {(access.warnings || []).map((w: string) => (
              <p key={w} className="text-xs" style={{ color: 'var(--wn)' }}>
                {w}
              </p>
            ))}
          </>
        )}
      </section>

      <section className="card space-y-2 p-4">
        <h3 className="font-extrabold">نقش فروشگاه</h3>
        {plan && (
          <>
            <p className="text-sm">
              نقش <span className="latin">{plan.role}</span> · {plan.applied ? 'اعمال شده' : 'اعمال نشده'}
            </p>
            <p className="text-xs text-[var(--mu)]">دسترسی‌های این نقش: {(plan.grants || []).join('، ') || '—'}</p>
            <p className="text-xs text-[var(--mu)]">محروم‌شده‌ها: {(plan.withheld || []).join('، ') || '—'}</p>
          </>
        )}
      </section>

      <section className="card space-y-2 p-4">
        <h3 className="font-extrabold">عملیات روی پنل</h3>
        <p className="text-xs text-[var(--mu)]">
          اعتبارنامه‌ی owner فقط برای همین درخواست فرستاده می‌شود و ذخیره نمی‌شود. برای تأیید، نام پنل را دقیق وارد
          کنید.
        </p>
        <input
          className="inp w-full"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          aria-label="نام پنل برای تأیید"
          placeholder={panelName ? `نام پنل: ${panelName}` : 'نام پنل'}
        />
        <Secret
          value={owner.api_key}
          onChange={(v: string) => setOwner((o) => ({ ...o, api_key: v }))}
          placeholder="کلید API ‏owner"
        />
        <div className="grid gap-2 sm:grid-cols-2">
          <input
            className="inp"
            dir="ltr"
            autoComplete="off"
            value={owner.username}
            onChange={(e) => setOwner((o) => ({ ...o, username: e.target.value }))}
            aria-label="نام کاربری owner"
            placeholder="یا نام کاربری owner"
          />
          <Secret
            value={owner.password}
            onChange={(v: string) => setOwner((o) => ({ ...o, password: v }))}
            placeholder="رمز owner"
          />
        </div>
        <input
          className="inp w-full"
          dir="ltr"
          value={roleName}
          onChange={(e) => setRoleName(e.target.value)}
          aria-label="نام نقش فروشگاه"
          placeholder="نام نقش فروشگاه (خالی = melorin-store)"
        />
        <div className="flex flex-wrap gap-2">
          <button
            className="btn"
            disabled={busy || !nameOk || !confirm}
            onClick={() => run('/service-access/provision', 'ساخت ادمین سرویس', {})}
          >
            ساخت ادمین سرویس
          </button>
          <button
            className="btn btn-g"
            disabled={busy || !nameOk || !confirm}
            onClick={() => run('/service-access/rotate', 'چرخش کلید سرویس', { needsOwner: true, danger: true })}
          >
            چرخش کلید
          </button>
          <button className="btn btn-g" disabled={busy} onClick={listKeys}>
            فهرست کلیدها
          </button>
          <button
            className="btn btn-g"
            disabled={busy || !nameOk || !confirm}
            onClick={() =>
              run('/store-role/apply', 'اعمال نقش فروشگاه', { extra: { role_name: roleName.trim() || null } })
            }
          >
            اعمال نقش فروشگاه
          </button>
          <button
            className="btn btn-g btn-d"
            disabled={busy || !nameOk || !confirm}
            onClick={() => run('/store-role/revert', 'بازگشت به نقش پیش‌فرض', { danger: true })}
          >
            بازگشت به نقش پیش‌فرض
          </button>
        </div>
        {keys && (
          <ul className="divide-y divide-[var(--bd)] text-sm">
            {keys.length === 0 && <li className="py-1 text-[var(--mu)]">کلیدی ثبت نشده است.</li>}
            {keys.map((k) => (
              <li key={String(k.id)} className="flex justify-between gap-2 py-1">
                <span className="latin">{String(k.name)}</span>
                <span className="text-xs text-[var(--mu)]">
                  {String(k.status)} · {String(k.request_count ?? 0)} درخواست
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
