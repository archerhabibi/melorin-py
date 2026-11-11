import { useState } from 'react';
import { StatusBadge } from '../ui.tsx';
import { J, card, btn, ghost, inp, SCOPES, EVENTS, useGet } from './ResellerData.tsx';
import type { Json } from '../types';

function Secret({ title, value, onClose }: { title?: Json; value?: Json; onClose?: Json }) {
  return (
    <div className="mb-4 rounded-2xl border border-danger/30 bg-danger-soft p-4 text-sm">
      <b>{title}</b> — فقط یک‌بار نمایش داده می‌شود:
      <code dir="ltr" className="latin mt-2 block break-all rounded-xl bg-surface p-3 text-xs">
        {value}
      </code>
      <div className="mt-2 flex gap-2">
        <button className={ghost} onClick={() => navigator.clipboard?.writeText(value)}>
          کپی
        </button>
        <button className={ghost} onClick={onClose}>
          بستن
        </button>
      </div>
    </div>
  );
}

export function Keys({ coreFetch, base, notify }: { coreFetch?: Json; base?: Json; notify?: Json }) {
  const [rows, reload] = useGet(coreFetch, `${base}/api-credentials`);
  const [f, setF] = useState({ name: '', scopes: ['catalog:read', 'orders:read'], rate: 120, ips: '' });
  const [secret, setSecret] = useState<Json>(null);
  const create = async () => {
    const r = await coreFetch(`${base}/api-credentials`, {
      method: 'POST',
      headers: J,
      body: JSON.stringify({
        name: f.name,
        scopes: f.scopes,
        rate_limit_per_minute: +f.rate,
        ip_allowlist: f.ips ? f.ips.split(/[\s,]+/).filter(Boolean) : null,
      }),
    });
    if (r.ok) {
      const d = await r.json();
      setSecret(d.api_key);
      setF({ ...f, name: '' });
      reload();
    } else notify('ساخت کلید ناموفق بود');
  };
  const act = async (c: Json, a: Json) => {
    if (a === 'revoke' && !window.confirm('کلید برای همیشه ابطال شود؟')) return;
    const r = await coreFetch(`${base}/api-credentials/${c.id}/${a}`, { method: 'POST' });
    if (r.ok) {
      if (a === 'rotate') setSecret((await r.json()).api_key);
      reload();
    } else notify('عملیات ناموفق بود');
  };
  const tog = (s: Json) =>
    setF({ ...f, scopes: f.scopes.includes(s) ? f.scopes.filter((x) => x !== s) : [...f.scopes, s] });
  return (
    <div>
      {secret && <Secret title="کلید API" value={secret} onClose={() => setSecret(null)} />}
      <div className={`${card} mb-4`}>
        <h4 className="font-extrabold">کلید جدید</h4>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          <input
            className={inp}
            placeholder="نام"
            value={f.name}
            onChange={(e) => setF({ ...f, name: e.target.value })}
          />
          <input
            className={inp}
            type="number"
            placeholder="محدودیت در دقیقه"
            value={f.rate}
            onChange={(e) => setF({ ...f, rate: Number(e.target.value) })}
          />
          <input
            dir="ltr"
            className={inp}
            placeholder="IP allowlist (اختیاری)"
            value={f.ips}
            onChange={(e) => setF({ ...f, ips: e.target.value })}
          />
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {SCOPES.map((s) => (
            <label key={s} className="latin flex items-center gap-1 rounded-full bg-surface2 px-3 py-1 text-xs">
              <input type="checkbox" checked={f.scopes.includes(s)} onChange={() => tog(s)} />
              {s}
            </label>
          ))}
        </div>
        <button disabled={f.name.length < 2 || !f.scopes.length} onClick={create} className={`${btn} mt-4`}>
          ساخت کلید
        </button>
      </div>
      <div className={`${card} overflow-x-auto`}>
        <table className="w-full min-w-[560px] text-right text-sm">
          <thead className="text-xs text-muted [&_th]:pb-3 [&_th]:font-bold">
            <tr>
              <th>نام</th>
              <th>پیشوند</th>
              <th>وضعیت</th>
              <th>آخرین استفاده</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {(rows || []).map((c: Json) => (
              <tr key={c.id} className="border-t border-line">
                <td className="py-3">{c.name}</td>
                <td className="latin">{c.key_prefix}…</td>
                <td>
                  <StatusBadge status={c.status} />
                </td>
                <td>{c.last_used_at ? new Date(c.last_used_at).toLocaleString('fa-IR') : '—'}</td>
                <td className="flex flex-wrap gap-1.5 py-2">
                  {c.status !== 'revoked' && (
                    <>
                      <button className={ghost} onClick={() => act(c, 'rotate')}>
                        چرخش
                      </button>
                      <button className={ghost} onClick={() => act(c, c.status === 'active' ? 'disable' : 'activate')}>
                        {c.status === 'active' ? 'غیرفعال' : 'فعال'}
                      </button>
                      <button className={ghost} onClick={() => act(c, 'revoke')}>
                        ابطال
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function Hooks({ coreFetch, base, notify }: { coreFetch?: Json; base?: Json; notify?: Json }) {
  const [rows, reload] = useGet(coreFetch, `${base}/webhooks`);
  const [f, setF] = useState({ url: '', events: ['order.completed'] });
  const [secret, setSecret] = useState<Json>(null);
  const [dl, setDl] = useState<Json>(null);
  const create = async () => {
    const r = await coreFetch(`${base}/webhooks`, { method: 'POST', headers: J, body: JSON.stringify(f) });
    if (r.ok) {
      const d = await r.json();
      d.secret && setSecret(d.secret);
      setF({ ...f, url: '' });
      reload();
    } else notify('ساخت وبهوک ناموفق بود (URL باید عمومی و HTTPS باشد)');
  };
  const call = async (e: Json, p: Json, m = 'POST', ok = 'انجام شد') => {
    const r = await coreFetch(`${base}/webhooks/${e.id}${p}`, { method: m, headers: J });
    if (r.ok) {
      notify(ok);
      if (p === '/rotate-secret') {
        const d = await r.json();
        d.secret && setSecret(d.secret);
      }
      reload();
    } else notify('ناموفق بود');
  };
  const toggleStatus = async (e: Json) => {
    const r = await coreFetch(`${base}/webhooks/${e.id}`, {
      method: 'PATCH',
      headers: J,
      body: JSON.stringify({ status: e.status === 'active' ? 'disabled' : 'active' }),
    });
    r.ok ? reload() : notify('ناموفق بود');
  };
  const deliveries = async (e: Json) => {
    const r = await coreFetch(`${base}/webhooks/${e.id}/deliveries`);
    setDl({ e, rows: r.ok ? await r.json() : [] });
  };
  const redeliver = async (d: Json) => {
    const r = await coreFetch(`${base}/webhooks/${dl.e.id}/deliveries/${d.id}/redeliver`, { method: 'POST' });
    notify(r.ok ? 'در صف ارسال مجدد قرار گرفت' : 'ناموفق بود');
  };
  const tog = (s: Json) =>
    setF({ ...f, events: f.events.includes(s) ? f.events.filter((x) => x !== s) : [...f.events, s] });
  return (
    <div>
      {secret && <Secret title="Signing secret" value={secret} onClose={() => setSecret(null)} />}
      <div className={`${card} mb-4`}>
        <h4 className="font-extrabold">وبهوک جدید</h4>
        <input
          dir="ltr"
          className={`${inp} mt-3`}
          placeholder="https://example.com/hook"
          value={f.url}
          onChange={(e) => setF({ ...f, url: e.target.value })}
        />
        <div className="mt-3 flex flex-wrap gap-2">
          {EVENTS.map((s) => (
            <label key={s} className="latin flex items-center gap-1 rounded-full bg-surface2 px-3 py-1 text-xs">
              <input type="checkbox" checked={f.events.includes(s)} onChange={() => tog(s)} />
              {s}
            </label>
          ))}
        </div>
        <button disabled={!f.url || !f.events.length} onClick={create} className={`${btn} mt-4`}>
          ساخت وبهوک
        </button>
      </div>
      {dl ? (
        <div className={card}>
          <button className="text-sm font-bold text-coral" onClick={() => setDl(null)}>
            → بازگشت
          </button>
          <h4 className="mt-2 font-extrabold latin" dir="ltr">
            {dl.e.url}
          </h4>
          <table className="mt-3 w-full text-right text-sm">
            <thead className="text-xs text-muted [&_th]:pb-3 [&_th]:font-bold">
              <tr>
                <th>رویداد</th>
                <th>وضعیت</th>
                <th>تلاش</th>
                <th>کد</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {dl.rows.map((d: Json) => (
                <tr key={d.id} className="border-t border-line">
                  <td className="latin py-2">{d.event_type}</td>
                  <td>
                    <StatusBadge status={d.status} />
                  </td>
                  <td>{d.attempts}</td>
                  <td>{d.last_status_code ?? '—'}</td>
                  <td>
                    <button className={ghost} onClick={() => redeliver(d)}>
                      ارسال مجدد
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="space-y-3">
          {(rows || []).map((e: Json) => (
            <div key={e.id} className={card}>
              <div className="latin break-all font-bold" dir="ltr">
                {e.url}
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted">
                <StatusBadge status={e.status} /> خطاهای پیاپی: {e.consecutive_failures} · {(e.events || []).join(', ')}
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                <button className={ghost} onClick={() => call(e, '/test', 'POST', 'رویداد تست ارسال شد')}>
                  تست
                </button>
                <button className={ghost} onClick={() => deliveries(e)}>
                  گزارش ارسال‌ها
                </button>
                <button className={ghost} onClick={() => call(e, '/rotate-secret', 'POST', 'Secret چرخید')}>
                  چرخش Secret
                </button>
                <button className={ghost} onClick={() => toggleStatus(e)}>
                  {e.status === 'active' ? 'غیرفعال' : 'فعال'}
                </button>
                <button className={ghost} onClick={() => window.confirm('حذف شود؟') && call(e, '', 'DELETE', 'حذف شد')}>
                  حذف
                </button>
              </div>
            </div>
          ))}
          {rows && !rows.length && (
            <div className="rounded-2xl border border-dashed border-line p-8 text-center text-sm text-muted">
              وبهوکی تعریف نشده
            </div>
          )}
        </div>
      )}
    </div>
  );
}
