// PasarGuard Phase 3 (PG-10 / PG-09) — admin account tools inside the account drawer: last seen, usage, devices, link rotation,
// suspend / resume, compensation and plan change. The tool matrix comes from the Core (/admin/vpn-accounts/{id}/tools): a tool the
// panel cannot serve is shown disabled with the Core's own reason. Connection IPs are never shown.
import { useCallback, useEffect, useState } from 'react';
import { Loader } from 'lucide-react';
import { confirmDialog, promptDialog } from './ui.tsx';
import { fmtBytes } from './dataKit.tsx';
import type { Json, Rec } from './types.ts';

const fmt = (v: Json) => (v ? new Date(v).toLocaleString('fa-IR') : '—');

export default function AccountToolsPanel({
  call,
  accountId,
  toast,
  onChanged,
}: {
  call?: Json;
  accountId?: Json;
  toast?: Json;
  onChanged?: Json;
}) {
  const base = `/api/v1/admin/vpn-accounts/${accountId}`;
  const [matrix, setMatrix] = useState<Json>(null);
  const [presence, setPresence] = useState<Json>(null);
  const [usage, setUsage] = useState<Json>(null);
  const [devices, setDevices] = useState<Json>(null);
  const [products, setProducts] = useState<Rec[]>([]);
  const [plan, setPlan] = useState('');
  const [adj, setAdj] = useState({ days: '', gb: '' });
  const [busy, setBusy] = useState('');

  const ok = (tool: Json) => matrix?.find((t: Json) => t.tool === tool);
  const can = (tool: Json) => ok(tool)?.available;

  const get = useCallback(
    async (path: Json) => {
      const r = await call(`${base}/tools${path}`);
      return r.ok ? r.json() : null;
    },
    [call, base],
  );

  const load = useCallback(async () => {
    const m = await get('');
    setMatrix(m);
    if (!m) return;
    const has = (t: Json) => m.find((x: Json) => x.tool === t)?.available;
    const [p, u, d] = await Promise.all([
      has('presence') ? get('/presence') : null,
      has('usage') ? get('/usage?period=day&days=30') : null,
      has('devices') ? get('/devices') : null,
    ]);
    setPresence(p);
    setUsage(u);
    setDevices(d);
  }, [get]);

  useEffect(() => {
    setMatrix(null);
    load();
  }, [load]);

  useEffect(() => {
    (async () => {
      try {
        const r = await call('/api/v1/admin/products');
        if (r.ok) setProducts(await r.json());
      } catch {
        /* the plan picker just stays empty */
      }
    })();
  }, [call]);

  const run = async (key: Json, url: Json, method: Json, body: Json, okText: Json) => {
    setBusy(key);
    try {
      const r = await call(url, { method, body: body ? JSON.stringify(body) : undefined });
      if (!r.ok) {
        const e = await r.json().catch(() => ({}));
        toast(e?.message || e?.detail || 'عملیات ناموفق بود');
      } else {
        toast(okText);
        await load();
        onChanged?.();
      }
    } catch {
      toast('ارتباط با سرور برقرار نشد');
    }
    setBusy('');
  };

  const withReason = async (message: Json, fn: Json) => {
    const reason = await promptDialog(message);
    if (reason && reason.trim().length >= 3) fn(reason.trim());
  };

  if (!matrix) return <p className="card p-4 text-sm">در حال دریافت ابزارها…</p>;

  const btn = (tool: Json, text: Json, onClick: Json, key = tool) => (
    <button
      key={key}
      className="btn btn-g"
      disabled={!can(tool) || !!busy}
      title={can(tool) ? '' : ok(tool)?.reason || ''}
      onClick={onClick}
    >
      {busy === key ? <Loader size={12} className="animate-spin" /> : null} {text}
    </button>
  );

  return (
    <div className="card space-y-3 p-4" aria-label="ابزارهای اکانت">
      <b>ابزارهای اکانت</b>
      {presence && (
        <div className="text-xs text-[var(--mu)]">
          {presence.never_connected
            ? 'هنوز هیچ اتصالی ثبت نشده'
            : `آخرین اتصال: ${fmt(presence.online_at)}${presence.online_now ? ' (آنلاین)' : ''}`}
          {presence.lifetime_used_bytes != null ? ` · مصرف کل: ${fmtBytes(presence.lifetime_used_bytes)}` : ''}
        </div>
      )}
      {usage && (
        <div className="text-xs text-[var(--mu)]">
          مصرف {usage.days} روز اخیر: <b>{fmtBytes(usage.total_bytes)}</b>
          {usage.by_node?.length ? ` · روی ${usage.by_node.length} نود` : ''}
        </div>
      )}
      {devices && (
        <div className="space-y-1">
          <div className="text-xs font-bold">دستگاه‌ها ({devices.count})</div>
          {devices.items.map((d: Json) => (
            <div key={d.hwid} className="flex items-center justify-between gap-2 text-xs">
              <span>
                {d.label}
                {d.platform ? ` · ${d.platform}` : ''} · آخرین بار {fmt(d.last_seen)}
              </span>
              <button
                className="btn btn-g"
                disabled={!can('devices_manage') || !!busy}
                onClick={async () => {
                  if (await confirmDialog('این دستگاه حذف شود؟', { danger: true }))
                    run(
                      `dev:${d.hwid}`,
                      `${base}/tools/devices/${encodeURIComponent(d.hwid)}`,
                      'DELETE',
                      null,
                      'دستگاه حذف شد',
                    );
                }}
              >
                حذف
              </button>
            </div>
          ))}
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {btn('devices_manage', 'ریست همه دستگاه‌ها', async () => {
          if (await confirmDialog('همه دستگاه‌های ثبت‌شده ریست شوند؟', { danger: true }))
            run('devices_manage', `${base}/tools/devices/reset`, 'POST', null, 'دستگاه‌ها ریست شد');
        })}
        {btn('rotate', 'لینک اشتراک جدید', async () => {
          if (await confirmDialog('لینک قبلی از کار می‌افتد. ادامه می‌دهید؟', { danger: true }))
            run('rotate', `${base}/tools/rotate-subscription`, 'POST', null, 'لینک جدید ساخته شد');
        })}
        {btn('suspend', 'تعلیق', () =>
          withReason('دلیل تعلیق را بنویسید', (reason: Json) =>
            run('suspend', `${base}/tools/suspend`, 'POST', { reason }, 'تعلیق شد'),
          ),
        )}
        {btn(
          'suspend',
          'فعال‌سازی مجدد',
          () => run('resume', `${base}/tools/resume`, 'POST', null, 'فعال شد'),
          'resume',
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <input
          aria-label="روز اضافه"
          className="inp !w-24"
          inputMode="numeric"
          placeholder="روز"
          value={adj.days}
          onChange={(e) => setAdj({ ...adj, days: e.target.value.replace(/\D/g, '') })}
        />
        <input
          aria-label="گیگ اضافه"
          className="inp !w-24"
          inputMode="numeric"
          placeholder="گیگ"
          value={adj.gb}
          onChange={(e) => setAdj({ ...adj, gb: e.target.value.replace(/\D/g, '') })}
        />
        {btn('adjust', 'جبران حجم/زمان', () =>
          withReason('دلیل جبران را بنویسید (ثبت در ممیزی)', (reason: Json) =>
            run(
              'adjust',
              `${base}/tools/adjust`,
              'POST',
              { add_days: Number(adj.days || 0), add_traffic_gb: Number(adj.gb || 0), reason },
              'جبران اعمال شد',
            ),
          ),
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label="پلن جدید" className="inp !w-auto" value={plan} onChange={(e) => setPlan(e.target.value)}>
          <option value="">پلن جدید…</option>
          {products.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <button
          className="btn btn-g"
          disabled={!plan || !can('change_plan') || !!busy}
          title={can('change_plan') ? '' : ok('change_plan')?.reason || ''}
          onClick={() =>
            withReason('دلیل تغییر پلن را بنویسید', (reason: Json) =>
              run('change_plan', `${base}/change-plan`, 'POST', { product_id: plan, reason }, 'پلن تغییر کرد'),
            )
          }
        >
          تغییر پلن
        </button>
      </div>
    </div>
  );
}
