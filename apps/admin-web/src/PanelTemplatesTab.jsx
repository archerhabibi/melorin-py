// PasarGuard Phase 3 (PG-09) — user templates mapped to packages: see drift, create / link / sync / disable / unlink.
// Melorin never edits a template it did not create (managed=false); every write is an audited admin action.
import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle, Loader, RefreshCw } from 'lucide-react';
import { confirmDialog } from './ui.jsx';

const DRIFT_LABEL = { data_limit: 'حجم', expire_duration: 'مدت', group_ids: 'گروه‌ها' };
const driftText = (k, v) =>
  `${DRIFT_LABEL[k] || k}: پکیج ${JSON.stringify(v.package)} ← پنل ${JSON.stringify(v.panel)}`;

export default function PanelTemplatesTab({ call, panelId, toast }) {
  const [data, setData] = useState(null);
  const [products, setProducts] = useState([]);
  const [pick, setPick] = useState('');
  const [busy, setBusy] = useState('');
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!panelId) return;
    setLoading(true);
    try {
      const [t, p] = await Promise.all([
        call(`/api/v1/admin/panels/${panelId}/templates`),
        call('/api/v1/admin/products'),
      ]);
      if (!t.ok) throw new Error(String(t.status));
      setData(await t.json());
      if (p.ok) setProducts(await p.json());
    } catch {
      toast('دریافت تمپلیت‌ها ناموفق بود');
    }
    setLoading(false);
  }, [call, panelId, toast]);

  useEffect(() => {
    setData(null);
    load();
  }, [load]);

  const act = async (key, path, method, body, okText) => {
    setBusy(key);
    try {
      const r = await call(`/api/v1/admin/panels/${panelId}/templates${path}`, {
        method,
        body: body ? JSON.stringify(body) : undefined,
      });
      if (!r.ok) {
        const e = await r.json().catch(() => ({}));
        toast(e?.message || e?.detail || 'عملیات ناموفق بود');
      } else {
        toast(okText);
        await load();
      }
    } catch {
      toast('ارتباط با سرور برقرار نشد');
    }
    setBusy('');
  };

  const unlink = async (m) => {
    if (
      !(await confirmDialog(`ارتباط پکیج «${m.product_name || ''}» با تمپلیت حذف شود؟ تمپلیت روی پنل می‌ماند.`, {
        danger: true,
      }))
    )
      return;
    act(`u:${m.product_id}`, `/${m.product_id}`, 'DELETE', null, 'ارتباط حذف شد');
  };

  if (!panelId) return <p className="card p-4 text-sm">برای دیدن تمپلیت‌ها یک پنل انتخاب کنید.</p>;
  if (!data) return <p className="card p-4 text-sm">{loading ? 'در حال دریافت…' : 'داده‌ای در دسترس نیست.'}</p>;

  const mappedIds = new Set(data.mappings.map((m) => m.product_id));
  const free = products.filter((p) => !mappedIds.has(p.id));

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-[var(--mu)]">
          هر پکیج می‌تواند به یک تمپلیت پنل وصل شود؛ تمدید پیش‌پرداخت و تغییر پلن از همین تمپلیت‌ها استفاده می‌کنند.
        </p>
        <button className="btn btn-g" disabled={loading} onClick={load}>
          <RefreshCw size={12} /> بازخوانی
        </button>
      </div>
      {data.error && (
        <p className="card flex items-center gap-2 p-4 text-sm">
          <AlertTriangle size={16} /> {data.error}
        </p>
      )}

      {data.mappings.length === 0 && <p className="card p-4 text-sm">هنوز پکیجی به تمپلیت وصل نشده.</p>}
      {data.mappings.map((m) => {
        const drift = m.drift ? Object.entries(m.drift) : [];
        return (
          <article key={m.product_id} className="card space-y-2 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                {m.exists_on_panel === false ? (
                  <AlertTriangle size={16} color="var(--bd)" />
                ) : (
                  <CheckCircle size={16} color="var(--ok)" />
                )}
                <b>{m.product_name || '—'}</b>
                <span className="text-xs text-[var(--mu)]">
                  ← تمپلیت #{m.remote_template_id} «{m.name}» {m.managed ? '(ساخته‌ی Melorin)' : '(موجود روی پنل)'}
                </span>
              </div>
              <div className="flex flex-wrap gap-2">
                {m.managed && drift.length > 0 && (
                  <button
                    className="btn btn-g"
                    disabled={!!busy}
                    onClick={() => act(`s:${m.product_id}`, `/${m.product_id}/sync`, 'POST', null, 'همگام شد')}
                  >
                    {busy === `s:${m.product_id}` ? <Loader size={12} className="animate-spin" /> : null} همگام‌سازی با
                    پکیج
                  </button>
                )}
                <button
                  className="btn btn-g"
                  disabled={!!busy}
                  onClick={() => act(`d:${m.product_id}`, `/${m.product_id}/disable`, 'POST', null, 'غیرفعال شد')}
                >
                  غیرفعال
                </button>
                <button
                  className="btn btn-g"
                  disabled={!!busy}
                  onClick={() => act(`e:${m.product_id}`, `/${m.product_id}/enable`, 'POST', null, 'فعال شد')}
                >
                  فعال
                </button>
                <button className="btn btn-g" disabled={!!busy} onClick={() => unlink(m)}>
                  حذف ارتباط
                </button>
              </div>
            </div>
            {m.exists_on_panel === false && (
              <div className="text-sm text-[var(--bd)]">این تمپلیت روی پنل پیدا نشد.</div>
            )}
            {drift.map(([k, v]) => (
              <div key={k} className="text-xs text-[var(--wn)]">
                اختلاف — {driftText(k, v)}
              </div>
            ))}
          </article>
        );
      })}

      <h3 className="font-bold">وصل کردن پکیج</h3>
      <div className="card flex flex-wrap items-center gap-2 p-4">
        <select aria-label="پکیج" className="inp !w-auto" value={pick} onChange={(e) => setPick(e.target.value)}>
          <option value="">یک پکیج انتخاب کنید…</option>
          {free.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <button
          className="btn"
          disabled={!pick || !!busy}
          onClick={() => act('create', '', 'POST', { product_id: pick }, 'تمپلیت ساخته شد')}
        >
          ساخت تمپلیت برای این پکیج
        </button>
        {data.unmapped.map((t) => (
          <button
            key={t.id}
            className="btn btn-g"
            disabled={!pick || !!busy}
            onClick={() => act(`l:${t.id}`, '/link', 'POST', { product_id: pick, remote_template_id: t.id }, 'وصل شد')}
          >
            وصل به #{t.id} «{t.name}»
          </button>
        ))}
      </div>
    </section>
  );
}
