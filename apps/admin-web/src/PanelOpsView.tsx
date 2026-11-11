// PasarGuard Phase 1+2+3 — panel operations (live events tab: PG-03; capacity PG-08; templates PG-09): real node health (PG-01), reconciliation issues (PG-04), unknown panel users (PG-04)
// and the connection's access review (PG-05). Everything comes from the Core API; every write is an explicit, audited admin action.
import { useCallback, useEffect, useState } from 'react';
import { Activity, AlertTriangle, CheckCircle, Loader, RefreshCw, ShieldAlert } from 'lucide-react';
import { authFetch } from './api.ts';
import { confirmDialog, promptDialog } from './ui.tsx';
import PanelEventsTab from './PanelEventsTab.tsx';
import PanelCapacityTab from './PanelCapacityTab.tsx';
import PanelTemplatesTab from './PanelTemplatesTab.tsx';
import PanelConsoleTab from './PanelConsoleTab.tsx';
import PanelPhase5Tab from './PanelPhase5Tab.tsx';
import type { CallFn, Json, Rec, Toast } from './types.ts';

const KIND_LABEL: Rec = {
  missing_on_panel: 'کاربر روی پنل نیست',
  panel_unreachable: 'پنل در دسترس نبود',
  owner_mismatch: 'مالک روی پنل اشتباه است',
  limits_mismatch: 'حجم/زمان روی پنل دستی تغییر کرده',
};
const ACTION_LABEL: Rec = {
  resync: 'بررسی مجدد',
  fix_owner: 'اصلاح مالک روی پنل',
  archive_account: 'بایگانی اکانت',
  resolve: 'بستن',
  ignore: 'نادیده گرفتن',
};
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
const LEVEL: Rec = {
  owner: { text: 'اتصال با حساب owner (بالاترین دسترسی)', color: 'var(--bd)' },
  limited: { text: 'دسترسی ناکافی برای بعضی قابلیت‌ها', color: 'var(--wn)' },
  unknown: { text: 'دسترسی‌ها هنوز بررسی نشده', color: 'var(--wn)' },
  least_privilege: { text: 'حداقل دسترسی لازم', color: 'var(--ok)' },
};
const fmt = (v: Json) => (v ? new Date(v).toLocaleString('fa-IR') : '—');
const gb = (n: Json) => `${((n || 0) / 2 ** 30).toFixed(1)} GB`;

const DETAIL_KEYS: Rec = { expected: 'مالک مورد انتظار', panel: 'مقدار روی پنل', username: 'نام کاربری', error: 'خطا' };
function Details({ d }: { d?: Json }) {
  if (!d) return null;
  const rows = Object.entries(d).map(([k, v]) => {
    const text =
      v && typeof v === 'object'
        ? `Melorin: ${(v as Rec).melorin ?? '—'} ← پنل: ${(v as Rec).panel ?? '—'}`
        : String(v);
    return (
      <div key={k}>
        <span className="text-[var(--mu)]">{DETAIL_KEYS[k] || k}: </span>
        {text}
      </div>
    );
  });
  return <div className="mt-1 text-xs">{rows}</div>;
}

// PG-06: when THIS store's customers are warned about low traffic (percent of the package used).
const DEFAULT_LEVELS_TEXT = '80, 90';
function NoticeLevels({ call, toast }: { call: CallFn; toast: Toast }) {
  const [stores, setStores] = useState<Rec[]>([]);
  const [storeId, setStoreId] = useState('');
  const [cfg, setCfg] = useState<Json>(null);
  const [text, setText] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const r = await call('/api/v1/admin/stores');
        if (r.ok) setStores(await r.json());
      } catch {
        toast('دریافت فهرست فروشگاه‌ها ناموفق بود');
      }
    })();
  }, [call, toast]);

  useEffect(() => {
    setCfg(null);
    if (!storeId) return;
    (async () => {
      try {
        const r = await call(`/api/v1/admin/stores/${storeId}/vpn-notices`);
        if (!r.ok) throw new Error(String(r.status));
        const j = await r.json();
        setCfg(j);
        setText(j.traffic_low_levels.join(', '));
      } catch {
        toast('دریافت تنظیمات هشدار ناموفق بود');
      }
    })();
  }, [call, storeId, toast]);

  const parse = () => {
    const parts = text.split(/[,،\s]+/).filter(Boolean);
    const nums = parts.map((x) => (/^\d+$/.test(x) ? Number(x) : NaN));
    return nums.some((n) => !(n >= 1 && n <= 99)) || nums.length > 4 ? null : nums;
  };

  const save = async (reset: Json) => {
    const levels = reset ? null : parse();
    if (!reset && levels === null) {
      toast('حداکثر ۴ عدد صحیح بین ۱ تا ۹۹ وارد کنید (با کاما جدا کنید)');
      return;
    }
    setSaving(true);
    try {
      const r = await call(`/api/v1/admin/stores/${storeId}/vpn-notices`, {
        method: reset ? 'DELETE' : 'PUT',
        body: reset ? undefined : JSON.stringify({ traffic_low_levels: levels }),
      });
      if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.error?.message || String(r.status));
      const j = await r.json();
      setCfg(j);
      setText(j.traffic_low_levels.join(', '));
      toast('ذخیره شد');
    } catch (e: Json) {
      toast(`ناموفق: ${e.message}`);
    }
    setSaving(false);
  };

  return (
    <section className="card space-y-3 p-4">
      <p className="text-sm">
        مشتریان هر فروشگاه وقتی درصد مصرف حجم اکانتشان به این عددها رسید، یک‌بار پیام می‌گیرند. پیش‌فرض:{' '}
        {DEFAULT_LEVELS_TEXT}. لیست خالی یعنی این فروشگاه هشدار حجم نمی‌فرستد.
      </p>
      <select className="inp" value={storeId} onChange={(e) => setStoreId(e.target.value)} aria-label="فروشگاه">
        <option value="">یک فروشگاه انتخاب کنید</option>
        {stores.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </select>
      {cfg && (
        <div className="flex flex-wrap items-center gap-2">
          <input
            className="inp"
            dir="ltr"
            value={text}
            onChange={(e) => setText(e.target.value)}
            aria-label="درصدهای هشدار"
            placeholder={DEFAULT_LEVELS_TEXT}
          />
          <button className="btn" disabled={saving} onClick={() => save(false)}>
            ذخیره
          </button>
          <button className="btn btn-g" disabled={saving || cfg.is_default} onClick={() => save(true)}>
            بازگشت به پیش‌فرض
          </button>
          <span className="text-xs text-[var(--mu)]">
            {cfg.is_default ? 'پیش‌فرض سامانه' : 'تنظیم اختصاصی این فروشگاه'}
          </span>
        </div>
      )}
    </section>
  );
}

export default function PanelOpsView({ api, toast }: { api?: Json; toast: Toast }) {
  const call = useCallback((p: string, o?: RequestInit) => authFetch(api.base, p, o), [api.base]);
  const [tab, setTab] = useState('issues');
  const [panels, setPanels] = useState<Rec[]>([]);
  const [panelId, setPanelId] = useState('');
  const [summary, setSummary] = useState<Json>(null);
  const [issues, setIssues] = useState<{ total: number; items: Rec[] }>({ total: 0, items: [] });
  const [orphans, setOrphans] = useState<{ total: number; items: Rec[] }>({ total: 0, items: [] });
  const [nodes, setNodes] = useState<Json>(null);
  const [busy, setBusy] = useState('');
  const [loading, setLoading] = useState(true);

  const getJ = useCallback(
    async (path: string) => {
      const r = await call(path);
      if (!r.ok) throw new Error(String(r.status));
      return r.json();
    },
    [call],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [pl, sm, is, orp] = await Promise.all([
        getJ('/api/v1/admin/panels'),
        getJ('/api/v1/admin/reconciliation/summary'),
        getJ(`/api/v1/admin/reconciliation/issues?limit=100${panelId ? `&panel_id=${panelId}` : ''}`),
        getJ(`/api/v1/admin/panel-orphans${panelId ? `?panel_id=${panelId}` : ''}`),
      ]);
      setPanels(pl.filter((p: Json) => p.kind === 'pasarguard'));
      setSummary(sm);
      setIssues(is);
      setOrphans(orp);
      if (panelId) setNodes(await getJ(`/api/v1/admin/panels/${panelId}/nodes`));
      else setNodes(null);
    } catch {
      toast('دریافت اطلاعات عملیات پنل ناموفق بود');
    }
    setLoading(false);
  }, [getJ, panelId, toast]);

  useEffect(() => {
    load();
  }, [load]);

  const selected = panels.find((p) => p.id === panelId);

  const act = async (issue: Json, action: Json) => {
    let reason: Json = null;
    if (action === 'ignore') {
      reason = await promptDialog('دلیل نادیده گرفتن این مغایرت را بنویسید (ثبت می‌شود).', { title: 'نادیده گرفتن' });
      if (!reason || !reason.trim()) return;
    } else if (action === 'archive_account') {
      if (
        !(await confirmDialog(`اکانت «${issue.username}» بایگانی می‌شود. هیچ چیزی روی پنل تغییر نمی‌کند.`, {
          danger: true,
        }))
      )
        return;
    } else if (action === 'fix_owner') {
      if (!(await confirmDialog(`مالک «${issue.username}» روی پنل به «${issue.details?.expected}» تغییر می‌کند.`)))
        return;
    }
    setBusy(`${issue.id}:${action}`);
    try {
      const r = await call(`/api/v1/admin/reconciliation/issues/${issue.id}/action`, {
        method: 'POST',
        body: JSON.stringify({ action, reason }),
      });
      if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.error?.message || String(r.status));
      toast('انجام شد');
      await load();
    } catch (e: Json) {
      toast(`ناموفق: ${e.message}`);
    }
    setBusy('');
  };

  const reconcileNow = async () => {
    if (!panelId) return;
    setBusy('reconcile');
    try {
      const r = await call(`/api/v1/admin/panels/${panelId}/reconcile`, { method: 'POST' });
      if (!r.ok) throw new Error(String(r.status));
      const d = await r.json();
      toast(d.unreachable ? 'پنل در دسترس نبود' : `${d.checked} اکانت بررسی شد، ${d.orphans} کاربر ناشناس`);
      await load();
    } catch {
      toast('همگام‌سازی ناموفق بود');
    }
    setBusy('');
  };

  const ignoreOrphan = async (o: Json) => {
    const note = await promptDialog('توضیح (اختیاری): این کاربر چرا مشکلی ندارد؟', { title: 'نادیده گرفتن کاربر پنل' });
    if (note === null) return;
    const r = await call(`/api/v1/admin/panel-orphans/${o.id}/ignore`, {
      method: 'POST',
      body: JSON.stringify({ note }),
    });
    toast(r.ok ? 'از فهرست حذف شد (روی پنل دست نخورد)' : 'ناموفق بود');
    if (r.ok) await load();
  };

  const access = selected?.capabilities?.access;
  const tabBtn = (key: Json, text: Json, count: Json) => (
    <button key={key} className={`btn ${tab === key ? '' : 'btn-g'}`} onClick={() => setTab(key)}>
      {text}
      {count > 0 ? ` (${count})` : ''}
    </button>
  );

  return (
    <div dir="rtl" className="mx-auto max-w-5xl space-y-5 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Activity size={24} />
          <h1 className="text-xl font-extrabold">عملیات پنل پاسارگارد</h1>
        </div>
        <div className="flex flex-wrap gap-2">
          <select className="inp" value={panelId} onChange={(e) => setPanelId(e.target.value)} aria-label="پنل">
            <option value="">همهٔ پنل‌ها</option>
            {panels.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <button className="btn btn-g" onClick={load} disabled={loading}>
            {loading ? <Loader size={14} className="animate-spin" /> : <RefreshCw size={14} />} به‌روزرسانی
          </button>
          <button
            className="btn"
            onClick={reconcileNow}
            disabled={!panelId || busy === 'reconcile'}
            title={panelId ? '' : 'یک پنل انتخاب کنید'}
          >
            {busy === 'reconcile' ? <Loader size={14} className="animate-spin" /> : null} همگام‌سازی همین الان
          </button>
        </div>
      </div>

      {access && access.level !== 'not_applicable' && (
        <section
          className="card p-4"
          style={{ borderInlineStart: `4px solid ${LEVEL[access.level]?.color || 'var(--mu)'}` }}
        >
          <div className="flex items-center gap-2 font-bold">
            <ShieldAlert size={18} /> {LEVEL[access.level]?.text}
            {access.role ? <span className="text-xs text-[var(--mu)]">(نقش: {access.role})</span> : null}
          </div>
          {access.warnings.map((w: Json) => (
            <p key={w.code} className="mt-1 text-sm">
              {w.message}
              {w.permissions.length > 0 && (
                <span className="text-xs text-[var(--mu)]"> — {w.permissions.join('، ')}</span>
              )}
            </p>
          ))}
        </section>
      )}

      {summary && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          {Object.entries(KIND_LABEL).map(([k, text]) => (
            <div key={k} className="card p-3 text-center">
              <div className="text-2xl font-extrabold">{summary.open[k] || 0}</div>
              <div className="text-xs text-[var(--mu)]">{text}</div>
            </div>
          ))}
          <div className="card p-3 text-center">
            <div className="text-2xl font-extrabold">{summary.orphans_open}</div>
            <div className="text-xs text-[var(--mu)]">کاربر ناشناس روی پنل</div>
          </div>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {tabBtn('issues', 'مغایرت‌ها', issues.total)}
        {tabBtn('orphans', 'کاربران ناشناس', orphans.total)}
        {tabBtn('nodes', 'نودها', 0)}
        {tabBtn('console', 'کنسول و اشتراک', 0)}
        {tabBtn('events', 'رویدادهای زنده', 0)}
        {tabBtn('capacity', 'ظرفیت و فروش', 0)}
        {tabBtn('templates', 'تمپلیت‌ها', 0)}
        {tabBtn('observe', 'شاخص و پشتیبان', 0)}
        {tabBtn('notices', 'هشدار حجم', 0)}
      </div>

      {tab === 'issues' && (
        <section className="space-y-3">
          {issues.items.length === 0 && (
            <p className="card flex items-center gap-2 p-4 text-sm">
              <CheckCircle size={16} /> مغایرت بازی وجود ندارد.
            </p>
          )}
          {issues.items.map((i) => (
            <article key={i.id} className="card p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <b>{KIND_LABEL[i.kind] || i.kind}</b> <span className="text-sm">— {i.username}</span>
                  <div className="text-xs text-[var(--mu)]">
                    {i.panel_name} · {i.store_name} · {i.occurrences} بار · آخرین بار {fmt(i.last_seen_at)}
                  </div>
                  <Details d={i.details} />
                </div>
                <div className="flex flex-wrap gap-2">
                  {i.allowed_actions.map((a: Json) => (
                    <button key={a} className="btn btn-g" disabled={!!busy} onClick={() => act(i, a)}>
                      {busy === `${i.id}:${a}` ? <Loader size={12} className="animate-spin" /> : null} {ACTION_LABEL[a]}
                    </button>
                  ))}
                </div>
              </div>
            </article>
          ))}
        </section>
      )}

      {tab === 'orphans' && (
        <section className="space-y-3">
          <p className="text-sm text-[var(--mu)]">
            کاربرانی که روی پنل هستند ولی Melorin نمی‌شناسد. هیچ‌چیز خودکار حذف نمی‌شود؛ فقط می‌توانید از فهرست پنهانشان
            کنید.
          </p>
          {orphans.items.length === 0 && <p className="card p-4 text-sm">کاربر ناشناسی پیدا نشد.</p>}
          {orphans.items.map((o) => (
            <article key={o.id} className="card flex flex-wrap items-center justify-between gap-2 p-4">
              <div>
                <b>{o.username}</b>
                <div className="text-xs text-[var(--mu)]">
                  {o.panel_name} · مالک: {o.owner_username || '—'} · وضعیت: {o.remote_status || '—'} · مصرف{' '}
                  {gb(o.traffic_used_bytes)} از {o.traffic_limit_bytes ? gb(o.traffic_limit_bytes) : 'نامحدود'} · انقضا{' '}
                  {fmt(o.expire_at)}
                </div>
              </div>
              <button className="btn btn-g" onClick={() => ignoreOrphan(o)}>
                نادیده گرفتن
              </button>
            </article>
          ))}
        </section>
      )}

      {tab === 'notices' && <NoticeLevels call={call} toast={toast} />}

      {tab === 'console' && <PanelConsoleTab call={call} panelId={panelId} toast={toast} />}
      {tab === 'observe' && <PanelPhase5Tab call={call} panelId={panelId} toast={toast} />}
      {tab === 'events' && <PanelEventsTab call={call} panelId={panelId} toast={toast} />}
      {tab === 'capacity' && <PanelCapacityTab call={call} panelId={panelId} toast={toast} />}
      {tab === 'templates' && <PanelTemplatesTab call={call} panelId={panelId} toast={toast} />}

      {tab === 'nodes' && (
        <section className="space-y-3">
          {!panelId && <p className="card p-4 text-sm">برای دیدن نودها یک پنل انتخاب کنید.</p>}
          {nodes && (
            <>
              <div className="card flex items-center gap-2 p-4 text-sm">
                <AlertTriangle size={16} />
                وضعیت پنل:{' '}
                <b>
                  {({ healthy: 'سالم', degraded: 'مختل', unhealthy: 'ناسالم' } as Rec)[nodes.health_status] ||
                    'بررسی‌نشده'}
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
      )}
    </div>
  );
}
