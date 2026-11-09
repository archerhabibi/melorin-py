// Reseller › Usage report. Everything here is what Core read from the VPN panel a moment ago (read-only).
// A panel that cannot answer shows "temporarily unavailable" and NO number: an old figure is never shown in its place.
// The report carries no IP, connection detail or subscription link, so none can appear on this screen.
import { useCallback, useEffect, useState } from 'react';
import { Activity, RefreshCw } from 'lucide-react';
import { Empty, Loading, StatusBadge, fa, fd } from './ui.jsx';

export const gb = (bytes) => {
  const n = Number(bytes) || 0;
  if (n >= 1024 ** 4) return `${fa((n / 1024 ** 4).toFixed(2))} ترابایت`;
  if (n >= 1024 ** 3) return `${fa((n / 1024 ** 3).toFixed(1))} گیگابایت`;
  return `${fa((n / 1024 ** 2).toFixed(0))} مگابایت`;
};
const STATES = [
  ['active', 'فعال'],
  ['on_hold', 'در انتظار اولین اتصال'],
  ['limited', 'حجم تمام‌شده'],
  ['expired', 'منقضی'],
  ['disabled', 'غیرفعال'],
  ['other', 'سایر'],
];

function Stat({ label, value, hint }) {
  return (
    <div className="card">
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-1 text-2xl font-extrabold">{value}</div>
      {hint && <div className="mt-1 text-xs text-muted">{hint}</div>}
    </div>
  );
}

export default function ResellerUsage({ coreFetch, base, notify }) {
  const [rep, setRep] = useState(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const r = await coreFetch(`${base}/usage-report`);
      if (!r.ok) throw new Error('load');
      setRep(await r.json());
      setFailed(false);
    } catch {
      setFailed(true);
      notify?.('گزارش مصرف دریافت نشد');
    } finally {
      setBusy(false);
    }
  }, [coreFetch, base, notify]);
  useEffect(() => {
    load();
  }, [load]);

  if (failed && !rep) return <Empty text="گزارش مصرف موقتاً در دسترس نیست." icon={Activity} />;
  if (!rep) return <Loading rows={3} />;

  const head = (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h4 className="flex items-center gap-2 font-extrabold">
        <Activity size={18} aria-hidden="true" /> گزارش مصرف فروشگاه
      </h4>
      <button type="button" className="btn-soft" onClick={load} disabled={busy}>
        <RefreshCw size={16} aria-hidden="true" /> به‌روزرسانی
      </button>
    </div>
  );
  if (!rep.live) {
    return (
      <div className="space-y-4">
        <div className="card space-y-2">
          {head}
          <p className="text-sm" role="status" data-testid="usage-unavailable">
            ⏳ {rep.note || 'اطلاعات زنده از پنل موقتاً در دسترس نیست.'} کمی بعد دوباره امتحان کنید.
          </p>
        </div>
      </div>
    );
  }
  const acc = rep.accounts || {};
  return (
    <div className="space-y-4" data-testid="usage-report">
      <div className="card space-y-2">
        {head}
        <p className="text-xs text-muted">
          اعداد همین لحظه از پنل خوانده شده‌اند (زمان: {fd(rep.taken_at)}). اطلاعات اتصال، آی‌پی یا لینک اشتراک مشتری در
          این گزارش نمایش داده نمی‌شود.
        </p>
        {rep.note && (
          <p className="text-sm text-danger" role="alert">
            {rep.note}
          </p>
        )}
        {!rep.complete && !rep.note && (
          <p className="text-sm text-muted">تعداد اکانت‌ها زیاد است؛ حجم نمایش‌داده‌شده فقط شامل پرمصرف‌ترین‌هاست.</p>
        )}
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="تعداد اکانت‌ها" value={fa(acc.total)} />
        <Stat label="مصرف کل" value={gb(rep.usage?.total_used_bytes)} />
        <Stat label="نزدیک انقضا" value={fa(rep.near_expiry)} hint={`تا ${fa(rep.near_expiry_days)} روز دیگر`} />
        <Stat
          label="نزدیک اتمام حجم"
          value={fa(rep.near_exhaustion)}
          hint={`بیش از ${fa(rep.near_exhaustion_percent)}٪ مصرف`}
        />
      </div>
      <div className="card">
        <h4 className="font-extrabold">وضعیت اکانت‌ها</h4>
        <ul className="mt-3 grid gap-2 text-sm sm:grid-cols-3">
          {STATES.map(([k, l]) => (
            <li key={k} className="flex items-center justify-between rounded-lg bg-surface2 px-3 py-2">
              <span>{l}</span>
              <b>{fa(acc[k])}</b>
            </li>
          ))}
        </ul>
      </div>
      <div className="card">
        <h4 className="font-extrabold">۵ مصرف‌کنندهٔ برتر</h4>
        {(rep.top_consumers || []).length === 0 ? (
          <p className="mt-2 text-sm text-muted">هنوز اکانتی ثبت نشده است.</p>
        ) : (
          <ol className="mt-3 space-y-2 text-sm">
            {rep.top_consumers.map((t, i) => (
              <li key={`${t.username}:${i}`} className="flex flex-wrap items-center justify-between gap-2">
                <span dir="ltr" className="latin break-all">
                  {fa(i + 1)}. {t.username}
                </span>
                <span className="flex items-center gap-2">
                  {gb(t.used_bytes)}
                  {t.limit_bytes > 0 ? ` از ${gb(t.limit_bytes)}` : ' (نامحدود)'}
                  <StatusBadge status={t.status} />
                </span>
              </li>
            ))}
          </ol>
        )}
      </div>
      {(rep.panels || []).some((p) => !p.ok) && (
        <p className="text-xs text-muted">
          پنل‌های بدون پاسخ:{' '}
          {(rep.panels || [])
            .filter((p) => !p.ok)
            .map((p) => p.name)
            .join('، ')}
        </p>
      )}
    </div>
  );
}
