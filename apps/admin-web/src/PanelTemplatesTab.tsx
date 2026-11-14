// PasarGuard Phase 3 (PG-09) — user templates mapped to packages: see drift, create / link / sync / disable / unlink.
// Melorin never edits a template it did not create (managed=false); every write is an audited admin action.
import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle, Loader, RefreshCw } from 'lucide-react';
import { confirmDialog } from './ui.tsx';
import { getJson, typedClient } from './api.ts';
import type { Json, Rec, Toast } from './types.ts';

const DRIFT_LABEL: Rec = { data_limit: 'حجم', expire_duration: 'مدت', group_ids: 'گروه‌ها' };
const driftText = (k: Json, v: Json) =>
  `${DRIFT_LABEL[k] || k}: پکیج ${JSON.stringify(v.package)} ← پنل ${JSON.stringify(v.panel)}`;

export default function PanelTemplatesTab({
  api,
  panelId,
  toast,
}: {
  api: { base: string };
  panelId?: Json;
  toast: Toast;
}) {
  const [data, setData] = useState<Json>(null);
  const [products, setProducts] = useState<Rec[]>([]);
  const [pick, setPick] = useState('');
  const [busy, setBusy] = useState('');
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!panelId) return;
    setLoading(true);
    try {
      const [t, p] = await Promise.all([
        getJson(api.base, `/api/v1/admin/panels/${panelId}/templates`),
        getJson(api.base, '/api/v1/admin/products').catch(() => null),
      ]);
      setData(t);
      if (p) setProducts(p);
    } catch {
      toast('دریافت تمپلیت‌ها ناموفق بود');
    }
    setLoading(false);
  }, [api.base, panelId, toast]);

  useEffect(() => {
    setData(null);
    load();
  }, [load]);

  // One typed call per action (literal path per endpoint); ``run`` returns the client result.
  const pid = (id?: string) => ({ path: { panel_id: String(panelId), product_id: String(id) } });
  const c = () => typedClient(api.base);
  const act = async (key: Json, run: () => Promise<Json>, okText: Json) => {
    setBusy(key);
    try {
      const { response: r, error } = await run();
      if (!r.ok) {
        const e = (error ?? {}) as { message?: string; detail?: string };
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

  const unlink = async (m: Json) => {
    if (
      !(await confirmDialog(`ارتباط پکیج «${m.product_name || ''}» با تمپلیت حذف شود؟ تمپلیت روی پنل می‌ماند.`, {
        danger: true,
      }))
    )
      return;
    act(
      `u:${m.product_id}`,
      () => c().delete('/api/v1/admin/panels/{panel_id}/templates/{product_id}', { params: pid(m.product_id) }),
      'ارتباط حذف شد',
    );
  };

  if (!panelId) return <p className="card p-4 text-sm">برای دیدن تمپلیت‌ها یک پنل انتخاب کنید.</p>;
  if (!data) return <p className="card p-4 text-sm">{loading ? 'در حال دریافت…' : 'داده‌ای در دسترس نیست.'}</p>;

  const mappedIds = new Set(data.mappings.map((m: Json) => m.product_id));
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
      {data.mappings.map((m: Json) => {
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
                    onClick={() =>
                      act(
                        `s:${m.product_id}`,
                        () =>
                          c().post('/api/v1/admin/panels/{panel_id}/templates/{product_id}/sync', {
                            params: pid(m.product_id),
                          }),
                        'همگام شد',
                      )
                    }
                  >
                    {busy === `s:${m.product_id}` ? <Loader size={12} className="animate-spin" /> : null} همگام‌سازی با
                    پکیج
                  </button>
                )}
                <button
                  className="btn btn-g"
                  disabled={!!busy}
                  onClick={() =>
                    act(
                      `d:${m.product_id}`,
                      () =>
                        c().post('/api/v1/admin/panels/{panel_id}/templates/{product_id}/disable', {
                          params: pid(m.product_id),
                        }),
                      'غیرفعال شد',
                    )
                  }
                >
                  غیرفعال
                </button>
                <button
                  className="btn btn-g"
                  disabled={!!busy}
                  onClick={() =>
                    act(
                      `e:${m.product_id}`,
                      () =>
                        c().post('/api/v1/admin/panels/{panel_id}/templates/{product_id}/enable', {
                          params: pid(m.product_id),
                        }),
                      'فعال شد',
                    )
                  }
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
          onClick={() =>
            act(
              'create',
              () =>
                c().post('/api/v1/admin/panels/{panel_id}/templates', {
                  params: { path: { panel_id: String(panelId) } },
                  body: { product_id: pick },
                }),
              'تمپلیت ساخته شد',
            )
          }
        >
          ساخت تمپلیت برای این پکیج
        </button>
        {data.unmapped.map((t: Json) => (
          <button
            key={t.id}
            className="btn btn-g"
            disabled={!pick || !!busy}
            onClick={() =>
              act(
                `l:${t.id}`,
                () =>
                  c().post('/api/v1/admin/panels/{panel_id}/templates/link', {
                    params: { path: { panel_id: String(panelId) } },
                    body: { product_id: pick, remote_template_id: t.id },
                  }),
                'وصل شد',
              )
            }
          >
            وصل به #{t.id} «{t.name}»
          </button>
        ))}
      </div>
    </section>
  );
}
