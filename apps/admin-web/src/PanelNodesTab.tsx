// Panel-scoped node health (PG-01): a tab of the panel detail drawer.
import { useEffect, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { getJson } from './api.ts';
import type { Json, Rec, Toast } from './types.ts';

const NODE_COLOR: Rec = {
  connected: 'var(--ok)',
  connecting: 'var(--wn)',
  disabled: 'var(--mu)',
  error: 'var(--bd)',
  limited: 'var(--bd)',
};
const NODE_LABEL: Rec = {
  connected: 'متصل',
  connecting: 'در حال اتصال',
  disabled: 'غیرفعال',
  error: 'خطا',
  limited: 'محدود',
  unknown: 'نامشخص',
};
const fmt = (v: Json) => (v ? new Date(v).toLocaleString('fa-IR') : '—');

export default function PanelNodesTab({
  api,
  panelId,
  toast,
}: {
  api: { base: string };
  panelId?: string;
  toast: Toast;
}) {
  const [nodes, setNodes] = useState<Json>(null);
  useEffect(() => {
    setNodes(null);
    if (!panelId) return;
    (async () => {
      try {
        setNodes(await getJson(api.base, `/api/v1/admin/panels/${panelId}/nodes`));
      } catch {
        toast('دریافت نودها ناموفق بود');
      }
    })();
  }, [api.base, panelId, toast]);
  return (
    <section className="space-y-3">
      {!panelId && <p className="card p-4 text-sm">برای دیدن نودها یک پنل انتخاب کنید.</p>}
      {nodes && (
        <>
          <div className="card flex items-center gap-2 p-4 text-sm">
            <AlertTriangle size={16} />
            وضعیت پنل:{' '}
            <b>
              {({ healthy: 'سالم', degraded: 'مختل', unhealthy: 'ناسالم' } as Rec)[nodes.health_status] || 'بررسی‌نشده'}
            </b>
            {nodes.detail?.reason ? <span>— {nodes.detail.reason}</span> : null}
            {nodes.detail?.sellable === false ? <b className="text-[var(--bd)]">(فروش جدید متوقف است)</b> : null}
          </div>
          {nodes.nodes.map((n: Json) => (
            <article key={n.remote_id} className="card p-4">
              <div className="flex items-center gap-2">
                <span
                  className="h-2.5 w-2.5 rounded-full"
                  style={{ background: NODE_COLOR[n.status] || 'var(--mu)' }}
                />
                <b>{n.name}</b>
                <span className="text-xs">{NODE_LABEL[n.status] || n.status}</span>
                <span className="text-xs text-[var(--mu)]">آخرین اتصال: {fmt(n.last_seen_at)}</span>
              </div>
              {n.message && <div className="mt-1 break-all text-xs text-[var(--mu)]">{n.message}</div>}
              {n.hint && <div className="mt-1 text-sm">{n.hint}</div>}
            </article>
          ))}
        </>
      )}
    </section>
  );
}
