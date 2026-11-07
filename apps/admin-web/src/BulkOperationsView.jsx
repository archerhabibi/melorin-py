// PasarGuard Phase 4 (PG-11) — bulk operations: preview -> type the exact count -> chunked run -> report -> resume.
// Everything runs in the Core API worker; this screen only plans, confirms and shows progress. Nothing here deletes an account.
import { useCallback, useEffect, useRef, useState } from 'react';
import { CheckCircle, Loader, RefreshCw, XCircle } from 'lucide-react';
import { authFetch } from './api.js';
import { confirmDialog } from './ui.jsx';

const KINDS = [
  ['extend_days', 'جبران زمان (افزودن روز)'],
  ['add_traffic', 'جبران حجم (افزودن گیگابایت)'],
  ['disable', 'غیرفعال‌سازی گروهی'],
  ['enable', 'فعال‌سازی گروهی'],
  ['reset_usage', 'ریست ترافیک'],
  ['rotate_links', 'چرخش لینک اشتراک'],
];
const STATUS_LABEL = { previewed: 'پیش‌نمایش', confirmed: 'در صف', running: 'در حال اجرا', done: 'کامل', partial: 'ناقص', failed: 'ناموفق', cancelled: 'لغو شد', expired: 'منقضی' };
const STATUS_COLOR = { previewed: 'var(--wn)', confirmed: 'var(--wn)', running: 'var(--wn)', done: 'var(--ok)', partial: 'var(--wn)', failed: 'var(--bd)', cancelled: 'var(--mu)', expired: 'var(--mu)' };
const SKIP_LABEL = { expired: 'منقضی‌شده', unlimited_time: 'زمان نامحدود', unlimited_traffic: 'حجم نامحدود' };
const fmt = (v) => (v ? new Date(v).toLocaleString('fa-IR') : '—');

async function readJson(r) {
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const err = new Error(data?.error?.message || data?.detail?.[0]?.msg || String(r.status));
    err.code = data?.error?.code;
    throw err;
  }
  return data;
}

export default function BulkOperationsView({ api, toast }) {
  const call = useCallback((p, o) => authFetch(api.base, p, o), [api.base]);
  const [panels, setPanels] = useState([]);
  const [stores, setStores] = useState([]);
  const [form, setForm] = useState({ panel_id: '', store_id: '', kind: 'extend_days', days: 3, gb: 5, expiring: '', reason: '' });
  const [plan, setPlan] = useState(null);
  const [typed, setTyped] = useState('');
  const [list, setList] = useState({ total: 0, items: [] });
  const [detail, setDetail] = useState(null);
  const [busy, setBusy] = useState('');
  const alive = useRef(true);

  useEffect(() => () => { alive.current = false; }, []);

  const loadList = useCallback(async () => {
    try {
      const l = await readJson(await call('/api/v1/admin/bulk-operations?limit=20'));
      if (alive.current) setList(l);
    } catch {
      toast('دریافت فهرست عملیات ناموفق بود');
    }
  }, [call, toast]);

  useEffect(() => {
    (async () => {
      try {
        const [p, s] = await Promise.all([readJson(await call('/api/v1/admin/panels')), readJson(await call('/api/v1/admin/stores'))]);
        const pg = p.filter((x) => x.kind === 'pasarguard');
        setPanels(pg);
        setStores(s);
        setForm((f) => ({ ...f, panel_id: f.panel_id || pg[0]?.id || '' }));
      } catch {
        toast('دریافت پنل‌ها ناموفق بود');
      }
    })();
    loadList();
  }, [call, loadList, toast]);

  // Running operations refresh themselves so the report moves without a click.
  useEffect(() => {
    const live = list.items.some((o) => ['confirmed', 'running'].includes(o.status));
    if (!live) return undefined;
    const t = setInterval(loadList, 5000);
    return () => clearInterval(t);
  }, [list, loadList]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const preview = async () => {
    setBusy('preview');
    setPlan(null);
    setTyped('');
    try {
      const selection = { panel_id: form.panel_id };
      if (form.store_id) selection.store_id = form.store_id;
      if (form.expiring !== '') selection.expiring_within_days = Number(form.expiring);
      const params = form.kind === 'extend_days' ? { days: Number(form.days) } : form.kind === 'add_traffic' ? { gb: Number(form.gb) } : undefined;
      setPlan(await readJson(await call('/api/v1/admin/bulk-operations/preview', { method: 'POST', body: JSON.stringify({ kind: form.kind, selection, params, reason: form.reason }) })));
    } catch (e) {
      toast(e.code === 'BULK_EMPTY' ? 'هیچ اکانت مناسبی پیدا نشد' : `پیش‌نمایش ناموفق: ${e.message}`);
    }
    setBusy('');
  };

  const confirm = async () => {
    setBusy('confirm');
    try {
      await readJson(await call(`/api/v1/admin/bulk-operations/${plan.id}/confirm`, { method: 'POST', body: JSON.stringify({ count: Number(typed) }) }));
      toast('در صف اجرا قرار گرفت');
      setPlan(null);
      setTyped('');
      await loadList();
    } catch (e) {
      toast(`تأیید ناموفق: ${e.message}`);
    }
    setBusy('');
  };

  const act = async (op, action, text) => {
    if (action === 'cancel' && !(await confirmDialog('این عملیات لغو شود؟ کارهای انجام‌شده برگردانده نمی‌شوند.', { danger: true, ok: 'لغو عملیات' }))) return;
    setBusy(`${action}-${op.id}`);
    try {
      await readJson(await call(`/api/v1/admin/bulk-operations/${op.id}/${action}`, { method: 'POST' }));
      toast(text);
      await loadList();
      if (detail?.id === op.id) await open(op);
    } catch (e) {
      toast(`ناموفق: ${e.message}`);
    }
    setBusy('');
  };

  const open = async (op) => {
    try {
      setDetail(await readJson(await call(`/api/v1/admin/bulk-operations/${op.id}?limit=100`)));
    } catch {
      toast('دریافت جزئیات ناموفق بود');
    }
  };

  const needsDays = form.kind === 'extend_days';
  const needsGb = form.kind === 'add_traffic';
  const canPreview = form.panel_id && form.reason.trim().length >= 3 && !busy;

  return (
    <div dir="rtl" className="mx-auto max-w-5xl space-y-5 p-6">
      <h1 className="text-xl font-extrabold">عملیات گروهی روی پنل</h1>
      <p className="text-sm text-[var(--mu)]">
        ابتدا پیش‌نمایش (چیزی ارسال نمی‌شود)، سپس تأیید با نوشتن تعداد دقیق. اجرا تکه‌تکه و قابل ازسرگیری است و هیچ اکانتی حذف نمی‌شود.
      </p>

      <section className="card space-y-3 p-4">
        <div className="grid gap-3 md:grid-cols-3">
          <label className="text-sm">پنل
            <select className="inp w-full" value={form.panel_id} onChange={set('panel_id')}>
              {panels.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
          <label className="text-sm">فروشگاه
            <select className="inp w-full" value={form.store_id} onChange={set('store_id')}>
              <option value="">همهٔ فروشگاه‌ها</option>
              {stores.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </label>
          <label className="text-sm">عملیات
            <select className="inp w-full" value={form.kind} onChange={set('kind')}>
              {KINDS.map(([k, t]) => <option key={k} value={k}>{t}</option>)}
            </select>
          </label>
          {needsDays && <label className="text-sm">تعداد روز<input className="inp w-full" type="number" min="1" max="90" value={form.days} onChange={set('days')} /></label>}
          {needsGb && <label className="text-sm">گیگابایت<input className="inp w-full" type="number" min="1" max="512" value={form.gb} onChange={set('gb')} /></label>}
          <label className="text-sm">فقط اکانت‌های نزدیک انقضا (روز، اختیاری)
            <input className="inp w-full" type="number" min="0" value={form.expiring} onChange={set('expiring')} />
          </label>
        </div>
        <label className="block text-sm">دلیل (در ممیزی ثبت می‌شود)
          <input className="inp w-full" value={form.reason} onChange={set('reason')} placeholder="مثلاً: قطعی نود ir24 در ۱۶ آبان" />
        </label>
        <button className="btn" onClick={preview} disabled={!canPreview}>
          {busy === 'preview' && <Loader size={14} className="animate-spin" />} پیش‌نمایش
        </button>
      </section>

      {plan && (
        <section className="card space-y-3 p-4" style={{ borderColor: 'var(--wn)' }}>
          <h2 className="font-bold">پیش‌نمایش: {plan.kind_label}</h2>
          <div className="text-sm">
            <b>{plan.total}</b> اکانت انتخاب شد
            {plan.skipped > 0 && (
              <span className="text-[var(--mu)]"> · {plan.skipped} مورد کنار گذاشته شد ({Object.entries(plan.selection?.skipped || {}).map(([k, n]) => `${SKIP_LABEL[k] || k}: ${n}`).join('، ')})</span>
            )}
          </div>
          <div className="text-xs text-[var(--mu)]">نمونه: {(plan.sample || []).join('، ')}</div>
          <div className="text-xs text-[var(--mu)]">این پیش‌نمایش تا {fmt(plan.expires_at)} معتبر است.</div>
          <div className="flex flex-wrap items-center gap-2">
            <input className="inp" inputMode="numeric" placeholder={`برای تأیید «${plan.total}» را بنویسید`} value={typed} onChange={(e) => setTyped(e.target.value.replace(/\D/g, ''))} />
            <button className="btn" onClick={confirm} disabled={Number(typed) !== plan.total || !!busy}>
              {busy === 'confirm' && <Loader size={14} className="animate-spin" />} تأیید و اجرا
            </button>
            <button className="btn btn-g" onClick={() => setPlan(null)}>انصراف</button>
          </div>
        </section>
      )}

      <section className="space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="font-bold">عملیات اخیر</h2>
          <button className="btn btn-g" onClick={loadList}><RefreshCw size={14} /> به‌روزرسانی</button>
        </div>
        {list.items.length === 0 && <p className="card p-3 text-sm">هنوز عملیاتی ثبت نشده است.</p>}
        {list.items.map((o) => (
          <article key={o.id} className="card p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <b>{o.kind_label}</b> <span className="text-xs text-[var(--mu)]">{o.panel_name}{o.store_name ? ` · ${o.store_name}` : ''}{o.origin === 'store_state' ? ' · از تعلیق فروشگاه' : ''}</span>
                <div className="text-xs text-[var(--mu)]">{fmt(o.created_at)} · {o.reason}</div>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-bold" style={{ color: STATUS_COLOR[o.status] }}>{STATUS_LABEL[o.status] || o.status}</span>
                <span className="text-xs">{o.succeeded}/{o.total}{o.failed ? ` · ${o.failed} خطا` : ''}{o.skipped ? ` · ${o.skipped} ردشده` : ''}</span>
                <button className="btn btn-g" onClick={() => open(o)}>جزئیات</button>
                {['partial', 'failed'].includes(o.status) && <button className="btn btn-g" disabled={!!busy} onClick={() => act(o, 'resume', 'ازسرگیری شد')}>ازسرگیری</button>}
                {['previewed', 'confirmed', 'running'].includes(o.status) && <button className="btn btn-g" disabled={!!busy} onClick={() => act(o, 'cancel', 'لغو شد')}>لغو</button>}
              </div>
            </div>
            {o.error && <div className="mt-1 text-xs" style={{ color: 'var(--bd)' }}>{o.error}</div>}
          </article>
        ))}
      </section>

      {detail && (
        <section className="card space-y-2 p-4">
          <div className="flex items-center justify-between">
            <h2 className="font-bold">گزارش: {detail.kind_label}</h2>
            <button className="btn btn-g" onClick={() => setDetail(null)}>بستن</button>
          </div>
          <div className="max-h-80 space-y-1 overflow-auto text-sm">
            {detail.items.map((i) => (
              <div key={i.username} className="flex items-center gap-2">
                {i.status === 'done' ? <CheckCircle size={14} style={{ color: 'var(--ok)' }} /> : i.status === 'failed' ? <XCircle size={14} style={{ color: 'var(--bd)' }} /> : <span className="inline-block w-3.5" />}
                <span dir="ltr">{i.username}</span>
                <span className="text-xs text-[var(--mu)]">{i.status}{i.error ? ` — ${i.error}` : ''}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
