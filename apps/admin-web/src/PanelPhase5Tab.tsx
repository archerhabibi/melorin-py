// PasarGuard Phase 5 — metrics (PG-14), settings drift + lifecycle policy (PG-15) and panel backup status (PG-16).
// Everything comes from the Core API (/admin/panels/{id}/metrics|settings-drift|lifecycle-policy, /admin/panel-backups).
// Nothing here writes a setting to the panel: "check now" is a read, the policy only changes what Melorin expects.
import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle, DatabaseBackup, Gauge, Info, Loader, RefreshCw } from 'lucide-react';
import { getJson, typedClient } from './api.ts';
import { promptDialog } from './ui.tsx';
import type { Json, Rec, Toast } from './types.ts';

const FINDING_COLOR: Rec = { ok: 'var(--ok)', drift: 'var(--bd)', info: 'var(--mu)', unknown: 'var(--wn)' };
const FINDING_LABEL: Rec = { ok: 'سالم', drift: 'ناهمخوان', info: 'اطلاع', unknown: 'نامشخص' };
const BACKUP_LABEL: Rec = { ok: 'سالم', stale: 'قدیمی یا ناموفق', not_configured: 'تنظیم نشده' };
const BACKUP_COLOR: Rec = { ok: 'var(--ok)', stale: 'var(--bd)', not_configured: 'var(--wn)' };
const fmt = (v: Json) => (v ? new Date(v).toLocaleString('fa-IR') : '—');
const pct = (v: Json) => (typeof v === 'number' ? `${Math.round(v * 100)}٪` : '—');

function ageText(seconds: Json) {
  if (seconds == null) return '—';
  if (seconds < 5400) return `${Math.max(1, Math.round(seconds / 60))} دقیقه پیش`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)} ساعت پیش`;
  return `${Math.round(seconds / 86400)} روز پیش`;
}

function Stat({ label, value, bad }: { label?: Json; value?: Json; bad?: Json }) {
  return (
    <div className="card p-3 text-center">
      <div className="text-xl font-extrabold" style={bad ? { color: 'var(--bd)' } : undefined}>
        {value}
      </div>
      <div className="text-xs text-[var(--mu)]">{label}</div>
    </div>
  );
}

function Readings({ data }: { data?: Json }) {
  if (!data) return null;
  const r = data.reading;
  const stale = data.taken_at && Date.now() - new Date(data.taken_at).getTime() > data.fresh_minutes * 60000;
  return (
    <section className="card space-y-3 p-4" aria-label="شاخص‌های پنل">
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 font-bold">
          <Gauge size={16} /> شاخص‌های زندهٔ پنل
        </h2>
        <span className="text-xs text-[var(--mu)]">آخرین خواندن: {fmt(data.taken_at)}</span>
      </div>
      {!r && <p className="text-sm text-[var(--mu)]">هنوز شاخصی ثبت نشده است (کار پس‌زمینه هر ۲ دقیقه می‌خواند).</p>}
      {stale && (
        <p className="flex items-center gap-1 text-sm" style={{ color: 'var(--wn)' }}>
          <AlertTriangle size={14} /> شاخص‌ها قدیمی‌اند؛ پنل در دسترس نیست یا کار شاخص‌ها متوقف شده است.
        </p>
      )}
      {r && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="وضعیت API" value={r.up ? 'در دسترس' : 'قطع'} bad={!r.up} />
          <Stat
            label="تأخیر API"
            value={r.latency_seconds != null ? `${r.latency_seconds.toFixed(2)} s` : '—'}
            bad={r.latency_seconds > 3}
          />
          <Stat label="کاربر آنلاین" value={r.online_users ?? '—'} />
          <Stat label="کاربران فعال" value={r.users?.active ?? '—'} />
          <Stat label="CPU" value={pct(r.cpu_ratio)} bad={r.cpu_ratio > 0.9} />
          <Stat label="حافظه" value={pct(r.mem_ratio)} bad={r.mem_ratio > 0.9} />
          <Stat label="دیسک" value={pct(r.disk_ratio)} bad={r.disk_ratio > 0.9} />
          {data.nodes && (
            <Stat
              label="نود متصل / خطا"
              value={`${data.nodes.connected} / ${data.nodes.error}`}
              bad={data.nodes.error > 0}
            />
          )}
        </div>
      )}
      {r?.insight_error && (
        <p className="text-xs text-[var(--mu)]">
          منابع پنل خوانده نشد (دسترسی system.read لازم است): {r.insight_error}
        </p>
      )}
      {r?.error && (
        <p className="text-xs" style={{ color: 'var(--bd)' }}>
          خطا: {r.error}
        </p>
      )}
    </section>
  );
}

function Drift({ api, panelId, toast }: { api: { base: string }; panelId?: Json; toast: Toast }) {
  const [d, setD] = useState<Json>(null);
  const [busy, setBusy] = useState('');

  const load = useCallback(async () => {
    try {
      setD(await getJson(api.base, `/api/v1/admin/panels/${panelId}/settings-drift`));
    } catch {
      toast('دریافت وضعیت تنظیمات پنل ناموفق بود');
    }
  }, [api.base, panelId, toast]);

  useEffect(() => {
    load();
  }, [load]);

  const check = async () => {
    setBusy('check');
    try {
      const { response: r, data } = await typedClient(api.base).post(
        '/api/v1/admin/panels/{panel_id}/settings-drift/check',
        { params: { path: { panel_id: String(panelId) } } },
      );
      if (r.ok) setD(data);
      toast(r.ok ? 'تنظیمات پنل خوانده و مقایسه شد (چیزی روی پنل نوشته نشد)' : 'خواندن تنظیمات ناموفق بود');
    } finally {
      setBusy('');
    }
  };

  const setPolicy = async (policy: Json) => {
    if (policy === d.policy) return;
    const reason = await promptDialog('دلیل تغییر سیاست حذف کاربران منقضی (برای ثبت در لاگ):', {
      title: 'سیاست پاک‌سازی کاربران منقضی',
    });
    if (reason === null) return;
    setBusy('policy');
    try {
      const { response: r, data } = await typedClient(api.base).put(
        '/api/v1/admin/panels/{panel_id}/lifecycle-policy',
        {
          params: { path: { panel_id: String(panelId) } },
          body: { policy, reason: String(reason ?? '').trim() },
        },
      );
      if (r.ok) setD(data);
      toast(r.ok ? 'سیاست ذخیره شد (فقط انتظار ملورین عوض شد، پنل دست نخورد)' : 'ذخیره سیاست ناموفق بود');
    } finally {
      setBusy('');
    }
  };

  if (!d) return <Loader className="animate-spin" size={18} />;
  return (
    <section className="card space-y-3 p-4" aria-label="ناهمخوانی تنظیمات">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 font-bold">
          {d.drifting > 0 ? (
            <AlertTriangle size={16} style={{ color: 'var(--bd)' }} />
          ) : (
            <CheckCircle size={16} style={{ color: 'var(--ok)' }} />
          )}
          تنظیمات پنل در برابر انتظار ملورین {d.drifting > 0 ? `(${d.drifting} ناهمخوانی)` : ''}
        </h2>
        <button className="btn btn-g" onClick={check} disabled={busy === 'check'}>
          {busy === 'check' ? <Loader size={14} className="animate-spin" /> : <RefreshCw size={14} />} بررسی اکنون
        </button>
      </div>
      <p className="text-xs text-[var(--mu)]">
        آخرین بررسی: {fmt(d.checked_at)} — این بخش فقط می‌خواند و هیچ تنظیمی را روی پنل نمی‌نویسد.
      </p>
      {d.error && (
        <p className="text-sm" style={{ color: 'var(--wn)' }}>
          خواندن آخرین بار ناموفق بود: {d.error}. نتیجهٔ قبلی تغییری نکرد.
        </p>
      )}
      <ul className="space-y-2">
        {d.findings.map((f: Json) => (
          <li key={f.key} className="flex items-start gap-2 text-sm">
            <span
              className="mt-0.5 rounded px-2 text-xs"
              style={{ background: FINDING_COLOR[f.state] || 'var(--mu)', color: '#fff' }}
            >
              {FINDING_LABEL[f.state] || f.state}
            </span>
            <span>{f.message}</span>
          </li>
        ))}
        {d.findings.length === 0 && <li className="text-sm text-[var(--mu)]">هنوز بررسی انجام نشده است.</li>}
      </ul>
      <div className="border-t pt-3">
        <div className="mb-1 flex items-center gap-1 text-sm font-bold">
          <Info size={14} /> حذف خودکار کاربران منقضی در پنل
        </div>
        <p className="mb-2 text-xs text-[var(--mu)]">
          اگر پنل کاربر منقضی را خودش پاک کند، ملورین آن را «گم‌شده روی پنل» می‌بیند. مهلت تمدید ملورین {d.grace_days}{' '}
          روز است.
        </p>
        <div className="flex flex-wrap gap-2">
          {d.policies.map((p: Json) => (
            <button
              key={p.value}
              className={`btn ${d.policy === p.value ? '' : 'btn-g'}`}
              disabled={busy === 'policy'}
              onClick={() => setPolicy(p.value)}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}

function Backup({ api, toast }: { api: { base: string }; toast: Toast }) {
  const [b, setB] = useState<Json>(null);
  const load = useCallback(async () => {
    try {
      setB(await getJson(api.base, '/api/v1/admin/panel-backups'));
    } catch {
      toast('دریافت وضعیت پشتیبان پنل ناموفق بود');
    }
  }, [api.base, toast]);
  useEffect(() => {
    load();
  }, [load]);
  if (!b) return <Loader className="animate-spin" size={18} />;
  return (
    <section className="card space-y-3 p-4" aria-label="پشتیبان پنل">
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 font-bold">
          <DatabaseBackup size={16} /> پشتیبان‌گیری از خود پنل پاسارگارد
        </h2>
        <span className="rounded px-2 text-xs" style={{ background: BACKUP_COLOR[b.state], color: '#fff' }}>
          {BACKUP_LABEL[b.state] || b.state}
        </span>
      </div>
      {b.state === 'not_configured' && (
        <p className="text-sm text-[var(--mu)]">
          پشتیبان پنل جدا از پشتیبان ملورین است و هنوز تنظیم نشده. متغیرهای MELORIN_PANEL_BACKUP_DATABASE_URL و
          MELORIN_PANEL_BACKUP_PATHS را طبق Runbook (بخش «پنل از دست رفت») تنظیم کنید.
        </p>
      )}
      <p className="text-sm">
        آخرین پشتیبان موفق: {fmt(b.last_success_at)} ({ageText(b.age_seconds)}) — بیشینهٔ مجاز {b.max_age_hours} ساعت
      </p>
      <ul className="space-y-1 text-xs">
        {b.runs.map((r: Json, i: Json) => (
          <li key={r.id || i} className="flex justify-between gap-2">
            <span>{fmt(r.created_at)}</span>
            <span style={{ color: r.status === 'succeeded' ? 'var(--ok)' : 'var(--bd)' }}>
              {r.status === 'succeeded' ? 'موفق' : 'ناموفق'}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function PanelPhase5Tab({
  api,
  panelId,
  toast,
}: {
  api: { base: string };
  panelId?: Json;
  toast: Toast;
}) {
  const [metrics, setMetrics] = useState<Json>(null);
  useEffect(() => {
    setMetrics(null);
    if (!panelId) return;
    (async () => {
      try {
        setMetrics(await getJson(api.base, `/api/v1/admin/panels/${panelId}/metrics`));
      } catch {
        toast('دریافت شاخص‌های پنل ناموفق بود');
      }
    })();
  }, [api.base, panelId, toast]);

  return (
    <div className="space-y-4">
      {panelId ? (
        <>
          <Readings data={metrics} />
          <Drift api={api} panelId={panelId} toast={toast} />
        </>
      ) : (
        <p className="card p-4 text-sm text-[var(--mu)]">
          برای دیدن شاخص‌ها و ناهمخوانی تنظیمات، یک پنل را از فهرست بالا انتخاب کنید.
        </p>
      )}
      <Backup api={api} toast={toast} />
    </div>
  );
}
