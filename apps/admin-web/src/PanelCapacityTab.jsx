// PasarGuard Phase 3 (PG-08) — real capacity and sellability: per-destination fill (Melorin count next to the panel's own count),
// per-group health with the reasons, and a "check now" action. Everything comes from /admin/panels/{id}/capacity*.
import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle, Loader, RefreshCw } from 'lucide-react';

const GROUP_LABEL = { healthy: 'سالم', degraded: 'مختل', blocked: 'مسدود' };
const GROUP_COLOR = { healthy: 'var(--ok)', degraded: 'var(--wn)', blocked: 'var(--bd)' };
const FILL_LABEL = { ok: 'عادی', warning: 'نزدیک پر شدن', critical: 'بحرانی', full: 'پر' };
const FILL_COLOR = { ok: 'var(--ok)', warning: 'var(--wn)', critical: 'var(--bd)', full: 'var(--bd)' };
const SOURCE_LABEL = { melorin: 'شمارش Melorin', panel: 'شمارش پنل', max: 'بیشترین مقدار دو شمارش' };
const fmt = (v) => (v ? new Date(v).toLocaleString('fa-IR') : '—');

export default function PanelCapacityTab({ call, panelId, toast }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!panelId) return;
    setLoading(true);
    try {
      const r = await call(`/api/v1/admin/panels/${panelId}/capacity`);
      if (!r.ok) throw new Error(String(r.status));
      setData(await r.json());
    } catch {
      toast('دریافت وضعیت ظرفیت ناموفق بود');
    }
    setLoading(false);
  }, [call, panelId, toast]);

  useEffect(() => {
    setData(null);
    load();
  }, [load]);

  const refresh = async () => {
    setBusy(true);
    try {
      const r = await call(`/api/v1/admin/panels/${panelId}/capacity/refresh`, { method: 'POST' });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) {
        toast(body?.message || body?.detail || 'بررسی ظرفیت ناموفق بود');
      } else {
        toast(body.changes?.length ? `${body.changes.length} تغییر ثبت شد` : 'تغییری نبود');
        await load();
      }
    } catch {
      toast('ارتباط با سرور برقرار نشد');
    }
    setBusy(false);
  };

  if (!panelId) return <p className="card p-4 text-sm">برای دیدن ظرفیت یک پنل انتخاب کنید.</p>;
  if (!data) return <p className="card p-4 text-sm">{loading ? 'در حال دریافت…' : 'داده‌ای در دسترس نیست.'}</p>;
  if (!data.capacity_ops)
    return <p className="card p-4 text-sm">این پنل بررسی ظرفیت واقعی را پشتیبانی نمی‌کند (فقط پاسارگارد).</p>;

  const groups = Object.entries(data.groups || {});
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-[var(--mu)]">
          فروش فقط به مقصدی انجام می‌شود که حداقل یک هاست فعال و یک نود متصل داشته باشد؛ اکانت‌های موجود تغییری
          نمی‌کنند.
        </p>
        <button className="btn btn-g" disabled={busy} onClick={refresh}>
          {busy ? <Loader size={12} className="animate-spin" /> : <RefreshCw size={12} />} بررسی همین حالا
        </button>
      </div>

      <h3 className="font-bold">سرورها (مقصدهای فروش)</h3>
      {data.servers.length === 0 && <p className="card p-4 text-sm">سروری روی این پنل تعریف نشده.</p>}
      {data.servers.map((s) => {
        const c = s.capacity_info;
        return (
          <article key={s.id} className="card space-y-2 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                {s.sellable ? (
                  <CheckCircle size={16} color="var(--ok)" />
                ) : (
                  <AlertTriangle size={16} color="var(--bd)" />
                )}
                <b>{s.name}</b>
                {!s.enabled && <span className="text-xs text-[var(--mu)]">(غیرفعال)</span>}
                <span className="text-xs" style={{ color: s.sellable ? 'var(--ok)' : 'var(--bd)' }}>
                  {s.sellable ? 'قابل فروش' : 'فروش متوقف'}
                </span>
              </div>
              <span className="text-xs text-[var(--mu)]">آخرین بررسی: {fmt(s.checked_at)}</span>
            </div>
            {s.sellable_reason && <div className="text-sm">{s.sellable_reason}</div>}
            <div className="flex flex-wrap items-center gap-3 text-xs">
              <span style={{ color: FILL_COLOR[c.state] }}>
                {c.capacity
                  ? `${c.used} از ${c.capacity} (${c.percent}٪) — ${FILL_LABEL[c.state]}`
                  : 'ظرفیت تعریف نشده'}
              </span>
              <span className="text-[var(--mu)]">Melorin: {c.melorin_accounts}</span>
              {c.panel_users != null && <span className="text-[var(--mu)]">کاربران پنل: {c.panel_users}</span>}
              {c.outside_melorin > 0 && <span className="text-[var(--wn)]">خارج از Melorin: {c.outside_melorin}</span>}
              <span className="text-[var(--mu)]">مبنا: {SOURCE_LABEL[c.source] || c.source || '—'}</span>
            </div>
          </article>
        );
      })}

      <h3 className="font-bold">گروه‌های پنل</h3>
      {data.groups == null && <p className="card p-4 text-sm">پنل پاسخ نداد؛ سلامت گروه‌ها نمایش داده نمی‌شود.</p>}
      {groups.map(([gid, g]) => (
        <article key={gid} className="card p-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: GROUP_COLOR[g.status] || 'var(--mu)' }} />
            <b>گروه {gid}</b>
            <span className="text-xs">{GROUP_LABEL[g.status] || g.status}</span>
            <span className="text-xs text-[var(--mu)]">
              امتیاز {g.score} · هاست فعال {g.hosts} · نود متصل {g.nodes}
              {g.total_users != null ? ` · کاربران ${g.total_users}` : ''}
            </span>
          </div>
          {g.reasons?.map((r) => (
            <div key={r} className="mt-1 text-xs text-[var(--mu)]">
              {r}
            </div>
          ))}
        </article>
      ))}
    </section>
  );
}
