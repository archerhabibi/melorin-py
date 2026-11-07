// PasarGuard Phase 4 (PG-12) — each store's panel admin: traffic cap, usage, panel status, and what a suspension does on the panel.
import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Loader, RefreshCw } from 'lucide-react';
import { authFetch } from './api.js';
import { promptDialog } from './ui.jsx';

const STATUS_LABEL = { active: 'فعال', disabled: 'غیرفعال', limited: 'سقف پر شده' };
const fmt = (v) => (v ? new Date(v).toLocaleString('fa-IR') : '—');
const gb = (n) => (n == null ? '—' : `${(n / 2 ** 30).toFixed(1)} GB`);

async function readJson(r) {
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data?.error?.message || data?.detail?.[0]?.msg || String(r.status));
  return data;
}

function Meter({ ratio }) {
  if (ratio == null) return <span className="text-xs text-[var(--mu)]">بدون سقف</span>;
  const tone = ratio >= 1 ? 'var(--bd)' : ratio >= 0.8 ? 'var(--wn)' : 'var(--ok)';
  return (
    <div className="h-2 w-40 overflow-hidden rounded-full bg-[var(--mb)]" role="progressbar" aria-valuenow={Math.round(ratio * 100)} aria-valuemin={0} aria-valuemax={100}>
      <div style={{ width: `${Math.min(100, ratio * 100)}%`, background: tone, height: '100%' }} />
    </div>
  );
}

export default function StoreGovernanceView({ api, toast }) {
  const call = useCallback((p, o) => authFetch(api.base, p, o), [api.base]);
  const [rows, setRows] = useState(null);
  const [busy, setBusy] = useState('');

  const load = useCallback(async () => {
    try {
      setRows((await readJson(await call('/api/v1/admin/store-admins'))).items);
    } catch (e) {
      toast(`دریافت فهرست ناموفق بود: ${e.message}`);
    }
  }, [call, toast]);

  useEffect(() => {
    load();
  }, [load]);

  const refresh = async () => {
    setBusy('refresh');
    try {
      const r = await readJson(await call('/api/v1/admin/store-admins/refresh', { method: 'POST' }));
      toast(`${r.updated} ادمین به‌روز شد${r.errors ? `، ${r.errors} خطا` : ''}`);
      await load();
    } catch (e) {
      toast(`ناموفق: ${e.message}`);
    }
    setBusy('');
  };

  const patch = async (row, body, okText) => {
    setBusy(row.id);
    try {
      await readJson(await call(`/api/v1/admin/store-admins/${row.id}`, { method: 'PATCH', body: JSON.stringify(body) }));
      toast(okText);
      await load();
    } catch (e) {
      toast(`ناموفق: ${e.message}`);
    }
    setBusy('');
  };

  const setCap = async (row) => {
    const v = await promptDialog(`سقف حجم «${row.store_name}» به گیگابایت (عدد مثبت). برای حذف سقف «0» بنویسید:`, { title: 'سقف حجم فروشگاه' });
    if (v == null || v === '') return;
    const n = Number(String(v).replace(/[۰-۹]/g, (d) => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d)));
    if (!Number.isFinite(n) || n < 0) return toast('عدد نامعتبر است');
    await patch(row, n === 0 ? { clear_limit: true } : { data_limit_gb: n }, 'سقف ثبت شد');
  };

  const toggleStatus = async (row) => {
    const next = row.remote_status === 'disabled' ? 'active' : 'disabled';
    const reason = await promptDialog(`ادمین «${row.store_name}» روی پنل ${next === 'disabled' ? 'غیرفعال می‌شود و فروشگاه نمی‌تواند اکانت بسازد' : 'دوباره فعال می‌شود'}. دلیل:`, { title: 'وضعیت ادمین روی پنل' });
    if (!reason) return;
    await patch(row, { status: next, reason }, 'وضعیت تغییر کرد');
  };

  const setPolicy = async (row, policy) => {
    setBusy(row.id);
    try {
      await readJson(await call(`/api/v1/admin/resellers/${row.store_id}/suspend-policy`, { method: 'PUT', body: JSON.stringify({ suspend_policy: policy }) }));
      toast('سیاست تعلیق ثبت شد');
      await load();
    } catch (e) {
      toast(`ناموفق: ${e.message}`);
    }
    setBusy('');
  };

  return (
    <div dir="rtl" className="mx-auto max-w-5xl space-y-5 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-extrabold">حجم و وضعیت ادمین فروشگاه‌ها روی پنل</h1>
        <button className="btn btn-g" onClick={refresh} disabled={!!busy}>
          {busy === 'refresh' ? <Loader size={14} className="animate-spin" /> : <RefreshCw size={14} />} خواندن مصرف از پنل
        </button>
      </div>
      <p className="text-sm text-[var(--mu)]">
        سقف حجم و وضعیت ادمین هر فروشگاه روی خود پنل اعمال می‌شود؛ فروشگاهی که به سقف برسد یا ادمینش غیرفعال باشد نمی‌تواند اکانت جدید بسازد.
      </p>
      {rows == null && <p className="card flex items-center gap-2 p-4 text-sm"><Loader size={14} className="animate-spin" /> در حال دریافت…</p>}
      {rows?.length === 0 && <p className="card p-4 text-sm">هنوز ادمین فروشگاهی روی پنل ساخته نشده است.</p>}
      {rows?.map((r) => (
        <article key={r.id} className="card space-y-2 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <b>{r.store_name}</b> <span className="text-xs text-[var(--mu)]">{r.panel_name} · <span dir="ltr">{r.username}</span></span>
              <div className="text-xs text-[var(--mu)]">
                وضعیت روی پنل: {STATUS_LABEL[r.remote_status] || r.remote_status || 'نامشخص'} · {r.total_users ?? '—'} کاربر · آخرین خواندن {fmt(r.usage_checked_at)}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <button className="btn btn-g" disabled={!!busy} onClick={() => setCap(r)}>سقف حجم</button>
              <button className="btn btn-g" disabled={!!busy} onClick={() => toggleStatus(r)}>{r.remote_status === 'disabled' ? 'فعال‌سازی روی پنل' : 'غیرفعال‌سازی روی پنل'}</button>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <Meter ratio={r.usage_ratio} />
            <span>{gb(r.used_traffic_bytes)} از {r.data_limit_bytes ? gb(r.data_limit_bytes) : 'نامحدود'}</span>
            {r.warning_level > 0 && <span style={{ color: 'var(--wn)' }}>به {r.warning_level}٪ سقف رسیده</span>}
          </div>
          {r.sell_blocked && (
            <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--bd)' }}><AlertTriangle size={14} /> {r.sell_blocked}</div>
          )}
          {r.error && <div className="text-xs" style={{ color: 'var(--bd)' }}>{r.error}</div>}
          <label className="flex items-center gap-2 text-sm">
            با تعلیق این فروشگاه:
            <select className="inp" value={r.suspend_policy || 'none'} disabled={!!busy} onChange={(e) => setPolicy(r, e.target.value)}>
              <option value="none">فقط فروش جدید بسته شود</option>
              <option value="disable_accounts">ادمین و اکانت‌های فعال روی پنل هم غیرفعال شوند</option>
            </select>
          </label>
        </article>
      ))}
    </div>
  );
}
