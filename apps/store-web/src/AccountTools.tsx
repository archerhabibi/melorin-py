// PasarGuard Phase 3 (PG-10): account tools for the customer ("my account") and the store owner ("my customer's account").
// One component for both: the tool matrix, the allowed actions and the data come from Core (`{base}/{id}/tools*`); a tool the
// panel cannot serve is simply not offered. Connection IPs are never part of this; "last seen" is owner-only. A write needs a
// second tap (inline confirmation), never a browser dialog.
import { useCallback, useState } from 'react';
import { Loader2, Wrench } from 'lucide-react';
import { fa, fd } from './ui.tsx';
import type { Json } from './types';

const gb = (b: Json) => (b ? (b / 1073741824).toFixed(2) : '0');

export default function AccountTools({
  a,
  base,
  coreFetch,
  notify,
  owner = false,
  onChange,
}: {
  a?: Json;
  base?: Json;
  coreFetch?: Json;
  notify?: Json;
  owner?: Json;
  onChange?: Json;
}) {
  const root = `${base}/${a.id}/tools`;
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<Json>(null);
  const [busy, setBusy] = useState('');
  const [ask, setAsk] = useState('');

  const getJ = useCallback(
    async (path: Json) => {
      const r = await coreFetch(`${root}${path}`);
      return r.ok ? r.json() : null;
    },
    [coreFetch, root],
  );

  const load = useCallback(async () => {
    const matrix = await getJ('');
    if (!matrix) return setData({ matrix: [], error: true });
    const ok = (t: Json) => matrix.find((x: Json) => x.tool === t)?.available;
    const [usage, devices, presence] = await Promise.all([
      ok('usage') ? getJ('/usage?period=day&days=30') : null,
      ok('devices') ? getJ('/devices') : null,
      owner && ok('presence') ? getJ('/presence') : null,
    ]);
    setData({ matrix, usage, devices, presence });
  }, [getJ, owner]);

  const toggle = () => {
    if (!open && !data) load();
    setOpen(!open);
  };

  const run = async (key: Json, path: Json, method: Json, okText: Json, readJson = false) => {
    setBusy(key);
    setAsk('');
    try {
      const r = await coreFetch(`${root}${path}`, {
        method,
        body: method === 'POST' && key === 'suspend' ? '{}' : undefined,
      });
      if (!r.ok) {
        const e = await r.json().catch(() => ({}));
        notify?.(e?.message || 'عملیات انجام نشد');
      } else {
        notify?.(okText);
        if (readJson) onChange?.(await r.json());
        await load();
      }
    } catch {
      notify?.('ارتباط با سرور برقرار نشد');
    }
    setBusy('');
  };

  const m = data?.matrix || [];
  const has = (t: Json) => m.find((x: Json) => x.tool === t)?.available;
  const confirmable = (key: Json, text: Json, go: Json) =>
    ask === key ? (
      <button className="btn-soft !py-2 text-xs text-danger" disabled={!!busy} onClick={go}>
        مطمئنید؟ دوباره بزنید
      </button>
    ) : (
      <button className="btn-soft !py-2 text-xs" disabled={!!busy} onClick={() => setAsk(key)}>
        {busy === key ? <Loader2 size={12} className="animate-spin" /> : null} {text}
      </button>
    );

  return (
    <div className="mt-2">
      <button onClick={toggle} aria-expanded={open} className="btn-soft w-full !py-2 text-xs">
        <Wrench size={14} /> ابزارهای اکانت
      </button>
      {open && (
        <div className="mt-2 space-y-3 rounded-xl bg-surface2 p-3 text-xs" aria-label="ابزارهای اکانت">
          {!data && <div>در حال دریافت…</div>}
          {data?.error && <div className="text-danger">ابزارها در دسترس نیست.</div>}
          {data?.presence && (
            <div className="text-muted">
              {data.presence.never_connected
                ? 'هنوز اتصالی ثبت نشده'
                : `آخرین اتصال: ${fd(data.presence.online_at)}${data.presence.online_now ? ' (آنلاین)' : ''}`}
            </div>
          )}
          {data?.usage && (
            <div>
              مصرف {fa(data.usage.days)} روز اخیر: <b>{gb(data.usage.total_bytes)} گیگ</b>
            </div>
          )}
          {data?.devices && (
            <div className="space-y-1">
              <b>دستگاه‌ها ({fa(data.devices.count)})</b>
              {data.devices.items.map((d: Json) => (
                <div key={d.hwid} className="flex items-center justify-between gap-2">
                  <span>
                    {d.label}
                    {d.platform ? ` · ${d.platform}` : ''}
                  </span>
                  {has('devices_manage') &&
                    confirmable(`dev:${d.hwid}`, 'حذف', () =>
                      run(`dev:${d.hwid}`, `/devices/${encodeURIComponent(d.hwid)}`, 'DELETE', 'دستگاه حذف شد'),
                    )}
                </div>
              ))}
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            {has('devices_manage') &&
              data?.devices?.count > 0 &&
              confirmable('reset', 'ریست همه دستگاه‌ها', () =>
                run('reset', '/devices/reset', 'POST', 'دستگاه‌ها ریست شد'),
              )}
            {has('rotate') &&
              confirmable('rotate', 'لینک اشتراک جدید', () =>
                run('rotate', '/rotate-subscription', 'POST', 'لینک جدید ساخته شد', true),
              )}
            {owner &&
              has('suspend') &&
              (a.status === 'suspended'
                ? confirmable('resume', 'فعال‌سازی مجدد', () => run('resume', '/resume', 'POST', 'اکانت فعال شد', true))
                : confirmable('suspend', 'تعلیق اکانت', () =>
                    run('suspend', '/suspend', 'POST', 'اکانت تعلیق شد', true),
                  ))}
          </div>
          {m.filter((t: Json) => !t.available && t.reason && t.tool !== 'adjust' && t.tool !== 'change_plan').length >
            0 && <div className="text-muted">برخی ابزارها برای این پنل فعال نیست.</div>}
        </div>
      )}
    </div>
  );
}
