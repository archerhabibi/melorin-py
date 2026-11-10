// PasarGuard Phase 2 (PG-03) — live events tab: connect/disconnect the panel's webhook, see queue health, browse and retry events.
// Everything comes from the Core API (/admin/panels/{id}/events*). The webhook secret is never shown: the API never returns it.
import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle, Loader, Radio, RefreshCw } from 'lucide-react';
import { confirmDialog } from './ui.tsx';
import type { Json, Rec } from './types.ts';

const ACTION_LABEL: Rec = {
  user_created: 'ساخت کاربر',
  user_updated: 'ویرایش کاربر',
  user_deleted: 'حذف کاربر',
  user_limited: 'اتمام حجم',
  user_expired: 'انقضا',
  user_enabled: 'فعال‌سازی',
  user_disabled: 'غیرفعال‌سازی',
  data_usage_reset: 'ریست مصرف',
  data_reset_by_next: 'ریست با پلن بعدی',
  subscription_revoked: 'تعویض لینک اشتراک',
  reached_usage_percent: 'رسیدن به درصد مصرف',
  reached_days_left: 'رسیدن به روز مانده',
};
const STATUS_LABEL: Rec = {
  pending: 'در صف',
  processing: 'در حال پردازش',
  processed: 'پردازش شد',
  ignored: 'نادیده',
  failed: 'ناموفق',
};
const STATUS_COLOR: Rec = {
  pending: 'var(--wn)',
  processing: 'var(--wn)',
  processed: 'var(--ok)',
  ignored: 'var(--mu)',
  failed: 'var(--bd)',
};
const fmt = (v: Json) => (v ? new Date(v).toLocaleString('fa-IR') : '—');

function silentText(seconds: Json) {
  if (seconds == null) return '—';
  if (seconds < 90) return 'همین حالا';
  if (seconds < 5400) return `${Math.round(seconds / 60)} دقیقه پیش`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)} ساعت پیش`;
  return `${Math.round(seconds / 86400)} روز پیش`;
}

const PAGE = 50;

export default function PanelEventsTab({ call, panelId, toast }: { call?: Json; panelId?: Json; toast?: Json }) {
  const [state, setState] = useState<Json>(null);
  const [events, setEvents] = useState<{ total: number; items: Rec[] }>({ total: 0, items: [] });
  const [filter, setFilter] = useState('');
  const [user, setUser] = useState('');
  const [busy, setBusy] = useState('');
  const [loading, setLoading] = useState(false);

  const getJ = useCallback(
    async (path: Json) => {
      const r = await call(path);
      if (!r.ok) throw new Error(String(r.status));
      return r.json();
    },
    [call],
  );

  const query = useCallback(
    (offset: Json) => {
      const q = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
      if (filter) q.set('status', filter);
      if (user.trim()) q.set('username', user.trim());
      return `/api/v1/admin/panels/${panelId}/events?${q}`;
    },
    [panelId, filter, user],
  );

  // Reloads state + the first page in place: the previous data stays on screen (no spinner swap, the filter inputs keep focus).
  const load = useCallback(
    async (live = false) => {
      if (!panelId) return;
      setLoading(true);
      try {
        const [st, ev] = await Promise.all([
          getJ(`/api/v1/admin/panels/${panelId}/events/status${live ? '?live=true' : ''}`),
          getJ(query(0)),
        ]);
        setState(st);
        setEvents(ev);
      } catch {
        toast('دریافت وضعیت رویدادها ناموفق بود');
      }
      setLoading(false);
    },
    [getJ, panelId, query, toast],
  );

  const more = async () => {
    setLoading(true);
    try {
      const ev = await getJ(query(events.items.length));
      setEvents((cur) => ({ total: ev.total, items: [...cur.items, ...ev.items] }));
    } catch {
      toast('دریافت رویدادهای بیشتر ناموفق بود');
    }
    setLoading(false);
  };

  // Only a different panel starts from the spinner; a filter change just refetches.
  useEffect(() => {
    setState(null);
    setEvents({ total: 0, items: [] });
  }, [panelId]);

  useEffect(() => {
    const t = setTimeout(load, user ? 300 : 0); // debounce typing in the username filter
    return () => clearTimeout(t);
  }, [load, user]);

  const post = async (key: Json, path: Json, body: Json, okText: Json) => {
    setBusy(key);
    try {
      const r = await call(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data?.error?.message || String(r.status));
      toast(okText(data));
      if (data && data.connected !== undefined) setState(data);
      await load();
    } catch (e: Json) {
      toast(`ناموفق: ${e.message}`);
    }
    setBusy('');
  };

  const connect = async (rotate: Json) => {
    const msg = rotate
      ? 'یک راز جدید ساخته و در تنظیمات خود پنل نوشته می‌شود. رازِ قبلی از کار می‌افتد.'
      : 'Melorin به‌عنوان مقصد وب‌هوک در تنظیمات خود پنل ثبت می‌شود (فقط همین یک تنظیم تغییر می‌کند).';
    if (!(await confirmDialog(msg, { title: rotate ? 'چرخش راز وب‌هوک' : 'اتصال رویدادهای زنده' }))) return;
    await post(
      'connect',
      `/api/v1/admin/panels/${panelId}/events/connect`,
      { confirm: true, rotate_secret: rotate },
      () => (rotate ? 'راز جدید ثبت شد' : 'رویدادهای زنده وصل شد'),
    );
  };

  const disconnect = async () => {
    if (
      !(await confirmDialog('مقصد Melorin از تنظیمات پنل حذف می‌شود. رویدادهای ذخیره‌شده همچنان پردازش می‌شوند.', {
        danger: true,
      }))
    )
      return;
    await post('disconnect', `/api/v1/admin/panels/${panelId}/events/disconnect`, null, () => 'قطع شد');
  };

  if (!panelId) return <p className="card p-4 text-sm">برای دیدن رویدادهای زنده یک پنل انتخاب کنید.</p>;
  if (!state)
    return (
      <p className="card flex items-center gap-2 p-4 text-sm">
        <Loader size={14} className="animate-spin" /> در حال دریافت…
      </p>
    );
  if (!state.supported) return <p className="card p-4 text-sm">رویداد زنده فقط برای پنل پاسارگارد پشتیبانی می‌شود.</p>;

  const c = state.counts || {};
  const silentAfter = state.silent_after_seconds || 6 * 3600;
  const silent = state.connected && state.silent_for_seconds != null && state.silent_for_seconds > silentAfter;

  return (
    <section className="space-y-3" data-testid="panel-events-tab">
      <div className="card space-y-2 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 font-bold">
            <Radio size={18} style={{ color: state.connected ? 'var(--ok)' : 'var(--mu)' }} />
            {state.connected ? 'رویدادهای زنده وصل است' : 'رویدادهای زنده وصل نیست'}
          </div>
          <div className="flex flex-wrap gap-2">
            {!state.connected && (
              <button className="btn" disabled={!!busy || !state.url} onClick={() => connect(false)}>
                {busy === 'connect' ? <Loader size={12} className="animate-spin" /> : null} اتصال
              </button>
            )}
            {state.connected && (
              <>
                <button className="btn btn-g" disabled={!!busy} onClick={() => load(true)}>
                  بررسی تنظیمات پنل
                </button>
                <button className="btn btn-g" disabled={!!busy} onClick={() => connect(true)}>
                  چرخش راز
                </button>
                <button className="btn btn-g" disabled={!!busy} onClick={disconnect}>
                  قطع اتصال
                </button>
              </>
            )}
          </div>
        </div>
        <div className="text-xs text-[var(--mu)]">
          آدرس دریافت: <span dir="ltr">{state.url || '—'}</span> · وصل‌شده: {fmt(state.connected_at)} · آخرین رویداد:{' '}
          {silentText(state.silent_for_seconds)}
        </div>
        {(state.warnings || []).map((w: Json, i: Json) => (
          <p key={`${i}-${w}`} className="flex items-start gap-2 text-sm">
            <AlertTriangle size={14} className="mt-1 shrink-0" style={{ color: 'var(--wn)' }} /> {w}
          </p>
        ))}
        {silent && (
          <p className="flex items-start gap-2 text-sm">
            <AlertTriangle size={14} className="mt-1 shrink-0" style={{ color: 'var(--wn)' }} />
            چند ساعت است رویدادی نرسیده؛ اگر پنل کاربر فعال دارد «بررسی تنظیمات پنل» را بزنید. همگام‌سازی ساعتی همچنان
            تضمین‌کنندهٔ همگرایی است.
          </p>
        )}
        {state.panel_side && state.panel_side.melorin_registered && (
          <p className="flex items-center gap-2 text-sm">
            <CheckCircle size={14} style={{ color: 'var(--ok)' }} /> پنل Melorin را به‌عنوان مقصد رویداد ثبت کرده است
            {state.panel_side.enabled ? '' : ' (اما وب‌هوک در پنل خاموش است)'}.
          </p>
        )}
      </div>

      <div className="grid grid-cols-3 gap-3 md:grid-cols-6">
        {['pending', 'processing', 'processed', 'ignored', 'failed'].map((k) => (
          <div key={k} className="card p-3 text-center">
            <div className="text-2xl font-extrabold">{c[k] || 0}</div>
            <div className="text-xs text-[var(--mu)]">{STATUS_LABEL[k]}</div>
          </div>
        ))}
        <div className="card p-3 text-center">
          <div className="text-2xl font-extrabold">{c.last_24h || 0}</div>
          <div className="text-xs text-[var(--mu)]">۲۴ ساعت اخیر</div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <select className="inp" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="وضعیت رویداد">
          <option value="">همهٔ وضعیت‌ها</option>
          {Object.entries(STATUS_LABEL).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <input
          className="inp"
          value={user}
          onChange={(e) => setUser(e.target.value)}
          placeholder="نام کاربری"
          aria-label="نام کاربری"
          dir="ltr"
        />
        <button className="btn btn-g" onClick={() => load()} disabled={loading}>
          {loading ? <Loader size={14} className="animate-spin" /> : <RefreshCw size={14} />} به‌روزرسانی
        </button>
        <button
          className="btn btn-g"
          disabled={!!busy || !(c.pending > 0)}
          onClick={() =>
            post(
              'process',
              `/api/v1/admin/panels/${panelId}/events/process`,
              null,
              (d: Json) => `${d.processed} رویداد پردازش شد`,
            )
          }
        >
          {busy === 'process' ? <Loader size={12} className="animate-spin" /> : null} پردازش صف
        </button>
        <button
          className="btn btn-g"
          disabled={!!busy || !(c.failed > 0)}
          onClick={() =>
            post(
              'retry',
              `/api/v1/admin/panels/${panelId}/events/retry-failed`,
              null,
              (d: Json) => `${d.requeued} رویداد دوباره در صف رفت`,
            )
          }
        >
          تلاش مجدد ناموفق‌ها
        </button>
      </div>

      {events.items.length === 0 && <p className="card p-4 text-sm">رویدادی ثبت نشده است.</p>}
      {events.items.map((e) => (
        <article key={e.id} className="card flex flex-wrap items-center justify-between gap-2 p-3">
          <div>
            <b>{ACTION_LABEL[e.action] || e.action}</b> <span className="text-sm">— {e.username || '—'}</span>
            <div className="text-xs text-[var(--mu)]">
              دریافت: {fmt(e.received_at)}
              {e.attempts > 0 ? ` · ${e.attempts} تلاش` : ''}
              {e.outcome ? ` · ${e.outcome}` : ''}
            </div>
          </div>
          <span className="text-xs font-bold" style={{ color: STATUS_COLOR[e.status] || 'var(--mu)' }}>
            {STATUS_LABEL[e.status] || e.status}
          </span>
        </article>
      ))}
      {events.items.length < events.total && (
        <button className="btn btn-g" onClick={more} disabled={loading}>
          نمایش بیشتر ({events.items.length} از {events.total})
        </button>
      )}
    </section>
  );
}
