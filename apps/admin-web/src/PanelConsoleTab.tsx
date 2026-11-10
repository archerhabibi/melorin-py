// PasarGuard Phase 4 (PG-07 console, PG-13 subscription test) — the panel's resources, live node stats and the few actions that fix a node
// without opening PasarGuard. Read-only by default; every action asks for a reason and is audited by the Core API.
import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle, Loader, RefreshCw, XCircle } from 'lucide-react';
import { confirmDialog, promptDialog } from './ui.tsx';
import type { Json, Rec } from './types.ts';

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
const CHECK_LABEL: Rec = {
  prefix: 'آدرس پایهٔ اشتراک',
  link_prefix: 'لینک اکانت واقعی',
  reachable: 'دسترسی‌پذیری',
  store_domains: 'دامنهٔ فروشگاه‌ها',
};
const STATE_ICON: Rec = { ok: CheckCircle, warn: AlertTriangle, fail: XCircle, skip: AlertTriangle };
const STATE_COLOR: Rec = { ok: 'var(--ok)', warn: 'var(--wn)', fail: 'var(--bd)', skip: 'var(--mu)' };
const fmt = (v: Json) => (v ? new Date(v).toLocaleString('fa-IR') : '—');
const bytes = (n: Json) => (n == null ? '—' : `${(n / 2 ** 30).toFixed(1)} GB`);
const pct = (v: Json) => (v == null ? '—' : `${Number(v).toFixed(0)}٪`);

async function readJson(r: Json) {
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data?.error?.message || data?.detail?.[0]?.msg || String(r.status));
  return data;
}

export default function PanelConsoleTab({ call, panelId, toast }: { call?: Json; panelId?: Json; toast?: Json }) {
  const [ov, setOv] = useState<Json>(null);
  const [infra, setInfra] = useState<Json>(null);
  const [sub, setSub] = useState<Json>(null);
  const [busy, setBusy] = useState('');
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!panelId) return;
    setLoading(true);
    try {
      const [o, s] = await Promise.all([
        call(`/api/v1/admin/panels/${panelId}/ops`).then(readJson),
        call(`/api/v1/admin/panels/${panelId}/subscription-check`).then(readJson),
      ]);
      setOv(o);
      setSub(s);
    } catch (e: Json) {
      toast(`دریافت کنسول ناموفق بود: ${e.message}`);
    }
    setLoading(false);
  }, [call, panelId, toast]);

  useEffect(() => {
    setOv(null);
    setInfra(null);
    setSub(null);
    load();
  }, [load]);

  const act = async (key: Json, path: Json, body: Json, okText: Json) => {
    setBusy(key);
    try {
      await readJson(await call(path, { method: 'POST', body: JSON.stringify(body) }));
      toast(okText);
      await load();
    } catch (e: Json) {
      toast(`ناموفق: ${e.message}`);
    }
    setBusy('');
  };

  const nodeAction = async (n: Json, action: Json) => {
    const text = action === 'reconnect' ? 'اتصال دوباره' : 'ارسال دوبارهٔ تنظیمات';
    const reason = await promptDialog(`«${n.name}»: ${text}. دلیل را بنویسید:`, { title: text });
    if (!reason) return;
    await act(
      `${action}-${n.remote_id}`,
      `/api/v1/admin/panels/${panelId}/ops/nodes/${n.remote_id}/${action}`,
      { reason },
      `${text} انجام شد`,
    );
  };

  const toggle = async (family: Json, row: Json, disabled: Json) => {
    const label = ({ nodes: 'نود', hosts: 'هاست', groups: 'گروه' } as Rec)[family];
    const reason = await promptDialog(
      `${disabled ? 'غیرفعال' : 'فعال'}‌کردن ${label} «${row.name || row.remark}». دلیل:`,
      { title: 'تغییر وضعیت' },
    );
    if (!reason) return;
    let force = false;
    const body = () => ({ ids: [row.id ?? row.remote_id], disabled, reason, force });
    const path = `/api/v1/admin/panels/${panelId}/ops/${family}/toggle`;
    setBusy(`${family}-${row.id ?? row.remote_id}`);
    try {
      let r = await call(path, { method: 'POST', body: JSON.stringify(body()) });
      let data = await r.json().catch(() => ({}));
      if (!r.ok && data?.error?.code === 'LAST_NODE') {
        const ok = await confirmDialog(data.error.message, {
          title: 'آخرین نود متصل',
          danger: true,
          ok: 'با مسئولیت من انجام شود',
        });
        if (!ok) {
          setBusy('');
          return;
        }
        force = true;
        r = await call(path, { method: 'POST', body: JSON.stringify(body()) });
        data = await r.json().catch(() => ({}));
      }
      if (!r.ok) throw new Error(data?.error?.message || String(r.status));
      toast('انجام شد');
      await load();
      if (infra) await loadInfra();
    } catch (e: Json) {
      toast(`ناموفق: ${e.message}`);
    }
    setBusy('');
  };

  const loadInfra = async () => {
    try {
      setInfra(await readJson(await call(`/api/v1/admin/panels/${panelId}/ops/infra`)));
    } catch (e: Json) {
      toast(`دریافت گروه‌ها و هاست‌ها ناموفق بود: ${e.message}`);
    }
  };

  const restartCore = async (core: Json) => {
    const typed = await promptDialog(
      `ری‌استارت هستهٔ «${core.name}» اتصال همهٔ کاربرانِ آن را لحظه‌ای قطع می‌کند. برای تأیید نام هسته را دقیقاً بنویسید:`,
      { title: 'ری‌استارت هسته' },
    );
    if (!typed) return;
    const reason = await promptDialog('دلیل ری‌استارت:', { title: 'ری‌استارت هسته' });
    if (!reason) return;
    await act(
      `core-${core.id}`,
      `/api/v1/admin/panels/${panelId}/ops/cores/${core.id}/restart`,
      { reason, confirm_name: typed },
      'هسته ری‌استارت شد',
    );
  };

  const runCheck = async () => {
    setBusy('sub');
    try {
      const r = await readJson(await call(`/api/v1/admin/panels/${panelId}/subscription-check`, { method: 'POST' }));
      setSub({ checked_at: new Date().toISOString(), result: r });
    } catch (e: Json) {
      toast(`آزمایش اشتراک ناموفق بود: ${e.message}`);
    }
    setBusy('');
  };

  if (!panelId) return <p className="card p-4 text-sm">برای دیدن کنسول یک پنل انتخاب کنید.</p>;
  if (!ov)
    return (
      <p className="card flex items-center gap-2 p-4 text-sm">
        <Loader size={14} className="animate-spin" /> در حال دریافت…
      </p>
    );
  const errs = Object.entries<string>(ov.errors || {});

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-bold">کنسول پنل</h2>
        <button className="btn btn-g" onClick={load} disabled={loading}>
          {loading ? <Loader size={14} className="animate-spin" /> : <RefreshCw size={14} />} به‌روزرسانی
        </button>
      </div>

      {errs.length > 0 && (
        <div className="card space-y-1 p-3 text-sm" style={{ borderColor: 'var(--wn)' }}>
          {errs.map(([k, v]) => (
            <div key={k} className="flex items-center gap-2">
              <AlertTriangle size={14} /> {v}
            </div>
          ))}
        </div>
      )}

      {ov.system && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {[
            ['نسخهٔ پنل', ov.system.version ?? '—'],
            ['کاربران آنلاین', ov.system.online_users ?? '—'],
            ['کاربران فعال', ov.system.active_users ?? '—'],
            ['CPU', pct(ov.system.cpu_usage)],
            ['RAM', ov.system.mem_total ? pct((100 * (ov.system.mem_used || 0)) / ov.system.mem_total) : '—'],
            ['کاربران منقضی', ov.system.expired_users ?? '—'],
            ['حجم‌تمام‌شده', ov.system.limited_users ?? '—'],
            ['غیرفعال', ov.system.disabled_users ?? '—'],
          ].map(([k, v]) => (
            <div key={k} className="card p-3">
              <div className="text-xs text-[var(--mu)]">{k}</div>
              <div className="text-lg font-extrabold">{v}</div>
            </div>
          ))}
        </div>
      )}

      <div className="space-y-2">
        <h3 className="text-sm font-bold">نودها</h3>
        {ov.nodes.length === 0 && <p className="card p-3 text-sm">نودی ثبت نشده است.</p>}
        {ov.nodes.map((n: Json) => (
          <article key={n.remote_id} className="card p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span
                  className="inline-block h-2.5 w-2.5 rounded-full"
                  style={{ background: NODE_COLOR[n.status] || 'var(--mu)' }}
                />
                <b>{n.name}</b>
                <span className="text-xs text-[var(--mu)]">{NODE_LABEL[n.status] || n.status}</span>
                {n.xray_version && <span className="text-xs text-[var(--mu)]">xray {n.xray_version}</span>}
              </div>
              <div className="flex flex-wrap gap-2">
                {ov.can.reconnect && (
                  <button className="btn btn-g" disabled={!!busy} onClick={() => nodeAction(n, 'reconnect')}>
                    {busy === `reconnect-${n.remote_id}` && <Loader size={12} className="animate-spin" />} اتصال دوباره
                  </button>
                )}
                {ov.can.infra && (
                  <>
                    <button className="btn btn-g" disabled={!!busy} onClick={() => nodeAction(n, 'sync')}>
                      همگام‌سازی
                    </button>
                    <button
                      className="btn btn-g"
                      disabled={!!busy}
                      onClick={() => toggle('nodes', { id: n.remote_id, name: n.name }, n.status !== 'disabled')}
                    >
                      {n.status === 'disabled' ? 'فعال‌سازی' : 'غیرفعال‌سازی'}
                    </button>
                  </>
                )}
              </div>
            </div>
            {n.message && (
              <div className="mt-1 text-xs" style={{ color: 'var(--bd)' }}>
                {n.message}
              </div>
            )}
            {n.hint && <div className="mt-1 text-xs">راه‌حل: {n.hint}</div>}
            {n.realtime && (
              <div className="mt-1 text-xs text-[var(--mu)]">
                CPU {pct(n.realtime.cpu_usage)} · ↑ {bytes(n.realtime.outgoing_bandwidth_speed)} · ↓{' '}
                {bytes(n.realtime.incoming_bandwidth_speed)}
              </div>
            )}
          </article>
        ))}
      </div>

      {ov.can.infra && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold">گروه‌ها، هاست‌ها و هسته‌ها</h3>
            <button className="btn btn-g" onClick={loadInfra}>
              {infra ? 'به‌روزرسانی' : 'نمایش'}
            </button>
          </div>
          {infra && (
            <div className="grid gap-3 md:grid-cols-3">
              <div className="card space-y-1 p-3">
                <div className="text-xs text-[var(--mu)]">گروه‌ها</div>
                {infra.groups.map((g: Json) => (
                  <div key={g.id} className="flex items-center justify-between text-sm">
                    <span>
                      {g.name} <span className="text-xs text-[var(--mu)]">({g.total_users ?? 0})</span>
                    </span>
                    <button className="btn btn-g" disabled={!!busy} onClick={() => toggle('groups', g, !g.disabled)}>
                      {g.disabled ? 'فعال' : 'غیرفعال'}
                    </button>
                  </div>
                ))}
              </div>
              <div className="card space-y-1 p-3">
                <div className="text-xs text-[var(--mu)]">هاست‌ها</div>
                {infra.hosts.map((h: Json) => (
                  <div key={h.id} className="flex items-center justify-between text-sm">
                    <span>{h.remark || h.inbound_tag}</span>
                    <button className="btn btn-g" disabled={!!busy} onClick={() => toggle('hosts', h, !h.disabled)}>
                      {h.disabled ? 'فعال' : 'غیرفعال'}
                    </button>
                  </div>
                ))}
              </div>
              <div className="card space-y-1 p-3">
                <div className="text-xs text-[var(--mu)]">هسته‌ها</div>
                {infra.cores.map((c: Json) => (
                  <div key={c.id} className="flex items-center justify-between text-sm">
                    <span>{c.name}</span>
                    <button className="btn btn-g" disabled={!!busy} onClick={() => restartCore(c)}>
                      ری‌استارت
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-bold">آزمایش یکپارچگی اشتراک</h3>
          <button className="btn" onClick={runCheck} disabled={busy === 'sub'}>
            {busy === 'sub' && <Loader size={14} className="animate-spin" />} اجرای آزمایش
          </button>
        </div>
        {!sub?.result && (
          <p className="card p-3 text-sm">
            هنوز آزمایش نشده. هیچ کاربری روی پنل ساخته نمی‌شود؛ فقط لینک یک اکانت واقعی بررسی می‌شود.
          </p>
        )}
        {sub?.result && (
          <div className="card space-y-2 p-3">
            <div className="text-xs text-[var(--mu)]">آخرین آزمایش: {fmt(sub.checked_at)}</div>
            {sub.result.checks.map((c: Json) => {
              const Icon = STATE_ICON[c.state] || AlertTriangle;
              return (
                <div key={c.name} className="flex items-start gap-2 text-sm">
                  <Icon size={16} style={{ color: STATE_COLOR[c.state], flexShrink: 0, marginTop: 2 }} />
                  <div>
                    <b>{CHECK_LABEL[c.name] || c.name}:</b> {c.message}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
