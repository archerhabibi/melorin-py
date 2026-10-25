import { useEffect, useRef, useState } from 'react';
import {
  ArrowRight,
  BarChart3,
  RefreshCw,
  X,
  Gauge,
  Bot,
  CreditCard,
  Eye,
  EyeOff,
  Globe,
  Settings,
  Tags,
  Users,
  Webhook,
  KeyRound,
  BellRing,
  Megaphone,
  ShieldCheck,
} from 'lucide-react';
import { Loading, PageTitle, StatusBadge, fa, fd } from './ui.jsx';
import Pricing from './ResellerPricing.jsx';
import AccountInquiry from './AccountInquiry.jsx';
import Broadcast from './ResellerBroadcast.jsx';
import EventCenter from './ResellerEventCenter.jsx';
import BankSms from './ResellerBankSms.jsx';
const J = { 'Content-Type': 'application/json' };

// The reseller renews his own accounts and HIS OWN store's customers' accounts. Core decides everything (window, package,
// price, wallet); this card shows Core's answer and asks Core to renew. The charge goes to the account holder's wallet.
function OwnerRenew({ account, base, coreFetch, notify, onDone, onClose }) {
  const [info, setInfo] = useState(null);
  const [busy, setBusy] = useState(false);
  const key = useRef(`web-owner-renew-${crypto.randomUUID()}`);
  useEffect(() => {
    let live = true;
    coreFetch(`${base}/accounts/${account.id}/renewal`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => live && setInfo(d))
      .catch(() => live && setInfo({ renewable: false, message: 'اطلاعات تمدید دریافت نشد.' }));
    return () => {
      live = false;
    };
  }, [account.id, base, coreFetch]);
  async function go() {
    setBusy(true);
    try {
      const r = await coreFetch(`${base}/accounts/${account.id}/renew`, {
        method: 'POST',
        headers: { ...J, 'Idempotency-Key': key.current },
        body: JSON.stringify({ channel: 'web' }),
      });
      if (!r.ok) return notify(await errOf(r, 'تمدید ناموفق بود'));
      notify('تمدید ثبت شد');
      onDone();
      onClose();
    } finally {
      setBusy(false);
    }
  }
  const after = info?.after;
  return (
    <div className="mt-4 rounded-xl bg-surface2 p-3 text-sm">
      <div className="flex items-center justify-between">
        <b>تمدید اکانت{account.is_own ? '' : ' مشتری'}</b>
        <button onClick={onClose} aria-label="بستن" className="text-muted">
          <X size={16} />
        </button>
      </div>
      {info === null ? (
        <Loading rows={1} />
      ) : !info.renewable ? (
        <p className="mt-2 text-xs text-muted">{info.message || 'این اکانت قابل تمدید نیست.'}</p>
      ) : (
        <div className="mt-2 space-y-1">
          <div>
            <b>{info.package.name}</b>
          </div>
          {after && (
            <div className="text-xs text-muted">
              پس از تمدید: {fa(after.duration_days)} روز ·{' '}
              {after.traffic_gb ? `${fa(after.traffic_gb)} گیگ` : 'نامحدود'}؛ روزهای باقی‌مانده فعلی جایگزین می‌شود،
              اضافه نمی‌شود.
            </div>
          )}
          <div className="mt-3 flex items-center justify-between gap-3 border-t border-line pt-3">
            <span>
              مبلغ:{' '}
              <b>
                {fa(info.package.price)} {info.package.currency}
              </b>
              {info.payer_note && <span className="block text-xs text-muted">{info.payer_note}</span>}
            </span>
            <button disabled={busy} onClick={go} className="btn-primary !px-4 !py-2 text-xs">
              تمدید
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function OwnerAccounts({ coreFetch, base, notify }) {
  const [renew, setRenew] = useState(null);
  const [tick, setTick] = useState(0);
  return (
    <AccountInquiry
      coreFetch={coreFetch}
      base={`${base}/accounts`}
      owner
      notify={notify}
      reloadKey={tick}
      emptyText="هنوز اکانتی نساخته‌اید. اکانت مشتریان را با جستجو پیدا کنید."
      renderExtra={(a) => (
        <>
          {a.can_renew ? (
            <button onClick={() => setRenew(renew === a.id ? null : a.id)} className="btn-soft mt-2 w-full">
              <RefreshCw size={16} />
              تمدید
            </button>
          ) : (
            a.renew_note && !a.is_test && <p className="mt-2 text-xs text-muted">{a.renew_note}</p>
          )}
          {renew === a.id && (
            <OwnerRenew
              account={a}
              base={base}
              coreFetch={coreFetch}
              notify={notify}
              onDone={() => setTick((t) => t + 1)}
              onClose={() => setRenew(null)}
            />
          )}
        </>
      )}
    />
  );
}
const card = 'card';
const btn = 'btn-primary !py-2.5';
const ghost = 'btn-ghost';
const inp = 'input !py-2.5';
const SCOPES = [
  'catalog:read',
  'customers:read',
  'customers:wallet:write',
  'orders:read',
  'wallet:read',
  'reports:read',
];
const EVENTS = [
  'order.completed',
  'order.refunded',
  'order.provisioning_failed',
  'payment.succeeded',
  'payment.failed',
  'wallet.changed',
  'vpn_account.expired',
  'vpn_account.near_expiry',
  'reseller.debt',
];

function useGet(coreFetch, path, deps = []) {
  const [d, setD] = useState(null);
  const [t, setT] = useState(0);
  useEffect(() => {
    if (!path) return;
    coreFetch(path)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(setD)
      .catch(() => setD([]));
  }, [path, t, coreFetch, ...deps]);
  return [d, () => setT((x) => x + 1)];
}

function Overview({ coreFetch, base }) {
  const [p] = useGet(coreFetch, `${base}/profile`);
  const [rep] = useGet(coreFetch, `${base}/reports`);
  const w = p?.main_wallet;
  return (
    <div className="grid gap-4 md:grid-cols-3">
      <div className="rounded-2xl bg-hero p-5 text-white">
        <div className="text-sm text-white/60">اعتبار کیف پول اصلی</div>
        <div className="mt-2 text-2xl font-extrabold" dir="ltr">
          {fa(w?.balance)} {w?.currency}
        </div>
        <div className="mt-2 text-xs text-accent">وضعیت بدهی: {w?.debt_state || '—'}</div>
      </div>
      <div className={card}>
        <div className="text-sm text-muted">سقف بدهی</div>
        <div className="mt-2 text-2xl font-extrabold">{fa(p?.debt_limit)}</div>
        <div className="mt-2 text-xs">
          فروش: {p?.sales_enabled ? 'فعال' : 'غیرفعال'} · API: {p?.api_enabled ? 'فعال' : 'غیرفعال'}
        </div>
      </div>
      <div className={card}>
        <div className="text-sm text-muted">فروشگاه</div>
        <div className="mt-2 text-xl font-extrabold">{p?.store_name || '—'}</div>
        <div className="mt-2 text-xs">ارز: {p?.store_currency}</div>
      </div>
      <div className={`${card} md:col-span-3`}>
        <h4 className="font-extrabold">گزارش سفارش‌ها</h4>
        <table className="mt-3 w-full text-right text-sm">
          <thead className="text-xs text-muted [&_th]:pb-3 [&_th]:font-bold">
            <tr>
              <th>وضعیت</th>
              <th>تعداد</th>
              <th>فروش</th>
              <th>بهای تمام‌شده</th>
            </tr>
          </thead>
          <tbody>
            {(rep?.orders || []).map((o) => (
              <tr key={o.status} className="border-t border-line">
                <td className="py-2.5">
                  <StatusBadge status={o.status} />
                </td>
                <td>{fa(o.count)}</td>
                <td>{fa(o.total)}</td>
                <td>{fa(o.reseller_cost)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Customers({ coreFetch, base, notify }) {
  const [rows, reload] = useGet(coreFetch, `${base}/customers`);
  const adjust = async (c) => {
    const amount = Number(window.prompt('مبلغ (مثبت = شارژ، منفی = اصلاح):', ''));
    if (!amount) return;
    const reason = window.prompt('دلیل:', '');
    if (!reason || reason.length < 3) return;
    const r = await coreFetch(`${base}/customers/${c.user_id}/wallet`, {
      method: 'POST',
      headers: J,
      body: JSON.stringify({ amount, reason, idempotency_key: `rs-${crypto.randomUUID()}` }),
    });
    notify(r.ok ? 'کیف پول مشتری به‌روز شد' : 'عملیات ناموفق بود');
    r.ok && reload();
  };
  return (
    <div className={`${card} overflow-x-auto`}>
      <table className="w-full min-w-[520px] text-right text-sm">
        <thead className="text-xs text-muted [&_th]:pb-3 [&_th]:font-bold">
          <tr>
            <th>نام</th>
            <th>ایمیل</th>
            <th>وضعیت</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {(rows || []).map((c) => (
            <tr key={c.user_id} className="border-t border-line">
              <td className="py-3">{c.display_name || '-'}</td>
              <td className="latin">{c.email || '-'}</td>
              <td>
                <StatusBadge status={c.status} />
              </td>
              <td>
                <button className={ghost} onClick={() => adjust(c)}>
                  شارژ/اصلاح کیف پول
                </button>
              </td>
            </tr>
          ))}
          {rows && !rows.length && (
            <tr>
              <td colSpan={4} className="p-8 text-center text-muted">
                مشتری‌ای وجود ندارد
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function Payments({ coreFetch, base, notify }) {
  const [rows, reload] = useGet(coreFetch, `${base}/payments`);
  const review = async (p, approve) => {
    const note = approve ? null : window.prompt('دلیل رد:', '');
    if (!approve && note === null) return;
    const r = await coreFetch(`${base}/payments/${p.id}/review`, {
      method: 'POST',
      headers: J,
      body: JSON.stringify({ approve, note }),
    });
    notify(r.ok ? 'ثبت شد' : 'بررسی ناموفق بود');
    r.ok && reload();
  };
  return (
    <div className={`${card} overflow-x-auto`}>
      <table className="w-full min-w-[520px] text-right text-sm">
        <thead className="text-xs text-muted [&_th]:pb-3 [&_th]:font-bold">
          <tr>
            <th>مبلغ</th>
            <th>درگاه</th>
            <th>وضعیت</th>
            <th>رسید</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {(rows || []).map((p) => (
            <tr key={p.id} className="border-t border-line">
              <td className="py-3">
                {fa(p.amount)} {p.currency}
              </td>
              <td>{p.provider}</td>
              <td>
                <StatusBadge status={p.status} />
              </td>
              <td>{p.has_receipt ? 'دارد' : 'ندارد'}</td>
              <td>
                {p.status !== 'succeeded' && p.status !== 'failed' && p.has_receipt ? (
                  <span className="flex gap-1.5">
                    <button className={ghost} onClick={() => review(p, true)}>
                      تأیید
                    </button>
                    <button className={ghost} onClick={() => review(p, false)}>
                      رد
                    </button>
                  </span>
                ) : (
                  ''
                )}
              </td>
            </tr>
          ))}
          {rows && !rows.length && (
            <tr>
              <td colSpan={5} className="p-8 text-center text-muted">
                پرداختی وجود ندارد
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function Secret({ title, value, onClose }) {
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

function Keys({ coreFetch, base, notify }) {
  const [rows, reload] = useGet(coreFetch, `${base}/api-credentials`);
  const [f, setF] = useState({ name: '', scopes: ['catalog:read', 'orders:read'], rate: 120, ips: '' });
  const [secret, setSecret] = useState(null);
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
  const act = async (c, a) => {
    if (a === 'revoke' && !window.confirm('کلید برای همیشه ابطال شود؟')) return;
    const r = await coreFetch(`${base}/api-credentials/${c.id}/${a}`, { method: 'POST' });
    if (r.ok) {
      if (a === 'rotate') setSecret((await r.json()).api_key);
      reload();
    } else notify('عملیات ناموفق بود');
  };
  const tog = (s) => setF({ ...f, scopes: f.scopes.includes(s) ? f.scopes.filter((x) => x !== s) : [...f.scopes, s] });
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
            onChange={(e) => setF({ ...f, rate: e.target.value })}
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
            {(rows || []).map((c) => (
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

function Hooks({ coreFetch, base, notify }) {
  const [rows, reload] = useGet(coreFetch, `${base}/webhooks`);
  const [f, setF] = useState({ url: '', events: ['order.completed'] });
  const [secret, setSecret] = useState(null);
  const [dl, setDl] = useState(null);
  const create = async () => {
    const r = await coreFetch(`${base}/webhooks`, { method: 'POST', headers: J, body: JSON.stringify(f) });
    if (r.ok) {
      const d = await r.json();
      d.secret && setSecret(d.secret);
      setF({ ...f, url: '' });
      reload();
    } else notify('ساخت وبهوک ناموفق بود (URL باید عمومی و HTTPS باشد)');
  };
  const call = async (e, p, m = 'POST', ok = 'انجام شد') => {
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
  const toggleStatus = async (e) => {
    const r = await coreFetch(`${base}/webhooks/${e.id}`, {
      method: 'PATCH',
      headers: J,
      body: JSON.stringify({ status: e.status === 'active' ? 'disabled' : 'active' }),
    });
    r.ok ? reload() : notify('ناموفق بود');
  };
  const deliveries = async (e) => {
    const r = await coreFetch(`${base}/webhooks/${e.id}/deliveries`);
    setDl({ e, rows: r.ok ? await r.json() : [] });
  };
  const redeliver = async (d) => {
    const r = await coreFetch(`${base}/webhooks/${dl.e.id}/deliveries/${d.id}/redeliver`, { method: 'POST' });
    notify(r.ok ? 'در صف ارسال مجدد قرار گرفت' : 'ناموفق بود');
  };
  const tog = (s) => setF({ ...f, events: f.events.includes(s) ? f.events.filter((x) => x !== s) : [...f.events, s] });
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
              {dl.rows.map((d) => (
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
          {(rows || []).map((e) => (
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

function Branding({ coreFetch, base, storeId, notify }) {
  const [b, setB] = useState({ title: '', primary_color: '#10233f', support_url: '' });
  const [msgs, setMsgs] = useState('{}');
  useEffect(() => {
    coreFetch(`/api/v1/stores/${storeId}`)
      .then((r) => (r.ok ? r.json() : {}))
      .then((s) => s.branding && setB((x) => ({ ...x, ...s.branding })));
  }, [storeId, coreFetch]);
  const save = async () => {
    let bot_messages;
    try {
      bot_messages = JSON.parse(msgs || '{}');
    } catch {
      return notify('پیام‌های ربات باید JSON معتبر باشند');
    }
    const body = { branding: b };
    if (msgs.trim() && msgs.trim() !== '{}') body.bot_messages = bot_messages;
    const r = await coreFetch(`${base}/branding`, { method: 'PATCH', headers: J, body: JSON.stringify(body) });
    notify(r.ok ? 'برندینگ ذخیره شد' : 'ذخیره ناموفق بود');
  };
  return (
    <div className={card}>
      <h4 className="font-extrabold">برندینگ فروشگاه</h4>
      <div className="mt-3 grid gap-3 md:grid-cols-3">
        <label className="text-xs font-bold">
          عنوان
          <input
            className={`${inp} mt-1`}
            value={b.title || ''}
            onChange={(e) => setB({ ...b, title: e.target.value })}
          />
        </label>
        <label className="text-xs font-bold">
          رنگ اصلی
          <input
            type="color"
            className={`${inp} mt-1 h-11`}
            value={b.primary_color || '#10233f'}
            onChange={(e) => setB({ ...b, primary_color: e.target.value })}
          />
        </label>
        <label className="text-xs font-bold">
          لینک پشتیبانی
          <input
            dir="ltr"
            className={`${inp} mt-1`}
            value={b.support_url || ''}
            onChange={(e) => setB({ ...b, support_url: e.target.value })}
          />
        </label>
      </div>
      <label className="mt-3 block text-xs font-bold">
        پیام‌های ربات (JSON، اختیاری)
        <textarea
          dir="ltr"
          rows={3}
          className={`${inp} mt-1 latin`}
          value={msgs}
          onChange={(e) => setMsgs(e.target.value)}
        />
      </label>
      <button onClick={save} className={`${btn} mt-4`}>
        ذخیره
      </button>
    </div>
  );
}

function PayConfig({ coreFetch, base, notify }) {
  const [rows, reload] = useGet(coreFetch, `${base}/payment-config`);
  const cur = (rows || []).find((r) => r.provider === 'manual_card');
  const [f, setF] = useState({ card_number: '', holder: '', bank: '', min_amount: '', max_amount: '', enabled: true });
  useEffect(() => {
    if (cur) setF((x) => ({ ...x, ...cur.public_config, enabled: cur.is_enabled }));
  }, [rows]);
  const save = async () => {
    const { enabled, ...pub } = f;
    ['min_amount', 'max_amount'].forEach((k) => {
      pub[k] = pub[k] === '' ? undefined : Number(pub[k]);
    });
    const r = await coreFetch(`${base}/payment-config/manual_card`, {
      method: 'PUT',
      headers: J,
      body: JSON.stringify({ is_enabled: enabled, public_config: pub }),
    });
    notify(r.ok ? 'اطلاعات کارت ذخیره شد' : 'ذخیره ناموفق بود');
    r.ok && reload();
  };
  const [zp, setZp] = useState('');
  const zcur = (rows || []).find((r) => r.provider === 'zarinpal');
  const saveZp = async () => {
    const r = await coreFetch(`${base}/payment-config/zarinpal`, {
      method: 'PUT',
      headers: J,
      body: JSON.stringify({ is_enabled: true, public_config: {}, secret: { merchant_id: zp } }),
    });
    notify(r.ok ? 'درگاه ذخیره شد' : 'ذخیره ناموفق بود');
    r.ok && (setZp(''), reload());
  };
  const fld = (k, l, t) => (
    <label className="text-xs font-bold">
      {l}
      <input
        type={t || 'text'}
        dir="ltr"
        className={`${inp} mt-1`}
        value={f[k] ?? ''}
        onChange={(e) => setF({ ...f, [k]: e.target.value })}
      />
    </label>
  );
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div className={card}>
        <h4 className="font-extrabold">کارت‌به‌کارت</h4>
        <div className="mt-3 grid gap-3">
          {fld('card_number', 'شماره کارت')}
          {fld('holder', 'صاحب کارت')}
          {fld('bank', 'بانک')}
          <div className="grid grid-cols-2 gap-3">
            {fld('min_amount', 'حداقل مبلغ', 'number')}
            {fld('max_amount', 'حداکثر مبلغ', 'number')}
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={f.enabled} onChange={(e) => setF({ ...f, enabled: e.target.checked })} />
            فعال
          </label>
        </div>
        <button onClick={save} className={`${btn} mt-4`}>
          ذخیره
        </button>
      </div>
      <div className={card}>
        <h4 className="font-extrabold">درگاه زرین‌پال</h4>
        <p className="mt-2 text-xs text-muted">
          وضعیت: {zcur ? (zcur.has_secret ? 'merchant ID ثبت شده' : 'بدون secret') : 'تنظیم نشده'} (مقدار ثبت‌شده هرگز
          نمایش داده نمی‌شود)
        </p>
        <input
          dir="ltr"
          className={`${inp} mt-3`}
          placeholder="Merchant ID جدید"
          value={zp}
          onChange={(e) => setZp(e.target.value)}
        />
        <button disabled={!zp} onClick={saveZp} className={`${btn} mt-3`}>
          ذخیره
        </button>
      </div>
    </div>
  );
}

async function errOf(r, fallback) {
  try {
    const d = await r.json();
    return (
      d?.error?.message ||
      (typeof d?.detail === 'string' ? d.detail : Array.isArray(d?.detail) ? 'اطلاعات واردشده معتبر نیست.' : '') ||
      fallback
    );
  } catch {
    return fallback;
  }
}
const DOMAIN_RE = /^(?!-)([a-z0-9-]{1,63}\.)+[a-z]{2,24}$/i;
const TOKEN_RE = /^\d{6,15}:[A-Za-z0-9_-]{30,64}$/;
const cleanDomain = (v) =>
  v
    .trim()
    .replace(/^[a-z]+:\/\//i, '')
    .split(/[/?#]/)[0]
    .replace(/\.$/, '')
    .toLowerCase();

function DetailsForm({ onSubmit, busy }) {
  const [f, setF] = useState({ domain: '', bot_token: '' });
  const [show, setShow] = useState(false);
  const domain = cleanDomain(f.domain);
  const token = f.bot_token.trim();
  const bad = { domain: f.domain && !DOMAIN_RE.test(domain), token: f.bot_token && !TOKEN_RE.test(token) };
  return (
    <div className="mt-4 grid gap-4">
      <p className="rounded-xl bg-accent-soft p-3 text-sm leading-7">
        درخواست شما تأیید شد. برای ساخت فروشگاه، دامنه و توکن ربات تلگرام را بفرستید (می‌توانید همین کار را در ربات
        تلگرام با دستور /reseller هم انجام دهید).
      </p>
      <label className="text-xs font-bold">
        <span className="flex items-center gap-1.5">
          <Globe size={14} />
          دامنهٔ فروشگاه
        </span>
        <input
          dir="ltr"
          className={`${inp} latin mt-1.5 ${bad.domain ? '!border-danger' : ''}`}
          placeholder="shop.example.com"
          value={f.domain}
          onChange={(e) => setF({ ...f, domain: e.target.value })}
          aria-invalid={!!bad.domain}
        />
      </label>
      <label className="text-xs font-bold">
        <span className="flex items-center gap-1.5">
          <Bot size={14} />
          توکن ربات تلگرام
        </span>
        <span className="relative mt-1.5 block">
          <input
            dir="ltr"
            type={show ? 'text' : 'password'}
            autoComplete="off"
            spellCheck={false}
            className={`${inp} latin !pl-11 ${bad.token ? '!border-danger' : ''}`}
            placeholder="123456789:AA…"
            value={f.bot_token}
            onChange={(e) => setF({ ...f, bot_token: e.target.value })}
            aria-invalid={!!bad.token}
          />
          <button
            type="button"
            onClick={() => setShow((x) => !x)}
            aria-label={show ? 'پنهان‌کردن توکن' : 'نمایش توکن'}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-muted"
          >
            {show ? <EyeOff size={17} /> : <Eye size={17} />}
          </button>
        </span>
      </label>
      <button
        className={btn}
        disabled={busy || !DOMAIN_RE.test(domain) || !TOKEN_RE.test(token)}
        onClick={() => onSubmit(domain, token)}
      >
        {busy ? 'در حال ساخت…' : 'ساخت فروشگاه'}
      </button>
    </div>
  );
}

function ApplicationCard({ a, onCancel, onDetails, busy }) {
  const pending = a.status === 'pending';
  const awaiting = a.status === 'awaiting_details';
  return (
    <div className={`${card} ${pending || awaiting ? 'border-accent/40' : ''}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs text-muted">{fd(a.created_at)}</div>
          <h4 className="mt-1 text-lg font-extrabold">{a.store_name}</h4>
        </div>
        <StatusBadge status={a.status} />
      </div>
      <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
        <div className="flex items-center gap-2">
          <Globe size={16} className="text-muted" />
          <dd dir="ltr" className="latin font-bold">
            {a.domain || '—'}
          </dd>
        </div>
        <div className="flex items-center gap-2">
          <Bot size={16} className="text-muted" />
          <dd dir="ltr" className="latin font-bold">
            {a.bot_username ? `@${a.bot_username}` : '—'}
          </dd>
        </div>
      </dl>
      {pending && (
        <p className="mt-4 rounded-xl bg-accent-soft p-3 text-sm leading-7">
          درخواست شما در صف بررسی مدیریت است. پس از تأیید، فروشگاه نمایندگی ساخته می‌شود و همین‌جا «پنل نماینده» برایتان
          باز می‌شود.
        </p>
      )}
      {(pending || awaiting || a.status === 'approved') && a.next_steps?.length > 0 && (
        <div className="mt-4 rounded-xl border border-line p-4">
          <h5 className="text-sm font-extrabold">کارهایی که باید انجام دهید</h5>
          <ol className="mt-3 space-y-2.5 text-sm leading-7">
            {a.next_steps.map((st, i) => (
              <li key={i} className={`flex gap-2 ${st.done ? 'text-muted line-through' : ''}`}>
                <span className="font-bold">{i + 1}.</span>
                <span>
                  <b>{st.title}</b> — {st.detail}
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}
      {awaiting && <DetailsForm onSubmit={(domain, token) => onDetails(a, domain, token)} busy={busy} />}
      {a.status === 'rejected' && (
        <p className="mt-4 rounded-xl bg-danger-soft p-3 text-sm leading-7">
          <b>دلیل رد:</b> {a.review_reason || '—'}
        </p>
      )}
      {(pending || awaiting) && (
        <button className={`${ghost} mt-4`} disabled={busy} onClick={() => onCancel(a)}>
          لغو درخواست
        </button>
      )}
    </div>
  );
}

function Apply({ coreFetch, notify, stores }) {
  const choices = (stores || []).filter((s) => s.status !== 'suspended');
  const [f, setF] = useState({
    store_name: '',
    message: '',
    domain: '',
    bot_token: '',
    target_store_id: choices.find((s) => s.kind === 'main')?.id || '',
  });
  const [apps, setApps] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [show, setShow] = useState(false);
  const loadApps = () =>
    coreFetch('/api/v1/reseller/applications')
      .then((r) => (r.ok ? r.json() : []))
      .then(setApps)
      .catch(() => setApps([]));
  useEffect(() => {
    loadApps();
  }, []);
  const domain = cleanDomain(f.domain);
  const token = f.bot_token.trim();
  const bad = { domain: f.domain && !DOMAIN_RE.test(domain), token: f.bot_token && !TOKEN_RE.test(token) };
  const reasonOk = f.message.trim().length >= 20;
  const ready =
    f.store_name.trim().length >= 2 && f.target_store_id && DOMAIN_RE.test(domain) && TOKEN_RE.test(token) && reasonOk;
  const send = async () => {
    setBusy(true);
    setErr('');
    try {
      const r = await coreFetch('/api/v1/reseller/applications', {
        method: 'POST',
        headers: J,
        body: JSON.stringify({
          ...f,
          store_name: f.store_name.trim(),
          domain,
          bot_token: token,
          message: f.message.trim(),
        }),
      });
      if (r.ok) {
        setF({ ...f, store_name: '', message: '', domain: '', bot_token: '' });
        notify('درخواست ثبت شد؛ منتظر بررسی بمانید');
        await loadApps();
      } else setErr(await errOf(r, 'ثبت درخواست ناموفق بود'));
    } catch {
      setErr('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy(false);
    }
  };
  const cancel = async (a) => {
    if (!window.confirm('درخواست لغو شود؟ می‌توانید بعداً دوباره ثبت کنید.')) return;
    setBusy(true);
    const r = await coreFetch(`/api/v1/reseller/applications/${a.id}/cancel`, { method: 'POST' });
    setBusy(false);
    notify(r.ok ? 'درخواست لغو شد' : 'لغو درخواست ناموفق بود');
    r.ok && loadApps();
  };
  const details = async (a, domain, token) => {
    setBusy(true);
    setErr('');
    try {
      const r = await coreFetch(`/api/v1/reseller/applications/${a.id}/details`, {
        method: 'POST',
        headers: J,
        body: JSON.stringify({ domain, bot_token: token }),
      });
      if (r.ok) {
        notify('فروشگاه نمایندگی ساخته شد');
        window.location.reload();
      } else {
        const m = await errOf(r, 'ثبت اطلاعات ناموفق بود');
        setErr(m);
        notify(m);
      }
    } catch {
      setErr('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy(false);
    }
  };
  if (apps === null) return <Loading rows={2} />;
  const open = (a) => a.status === 'pending' || a.status === 'awaiting_details';
  const pending = apps.find(open);
  const history = apps.filter((a) => !open(a)).slice(0, 3);
  return (
    <div className="mx-auto max-w-2xl space-y-5">
      {pending ? (
        <>
          <ApplicationCard a={pending} onCancel={cancel} onDetails={details} busy={busy} />
          {err && (
            <p role="alert" className="rounded-xl bg-danger-soft p-3 text-sm text-danger">
              {err}
            </p>
          )}
        </>
      ) : (
        <div className={card}>
          <h3 className="text-xl font-extrabold">درخواست نمایندگی</h3>
          <p className="mt-2 text-sm leading-7 text-muted">
            فروشگاه و ربات تلگرام اختصاصی خودت را داشته باش. فقط برای فروشگاهی درخواست بده که عضو فعال آن هستی؛ برای چند
            فروشگاه می‌توانی جداگانه درخواست بدهی.
          </p>
          <div className="mt-5 grid gap-4">
            {choices.length > 1 && (
              <label className="text-xs font-bold">
                فروشگاه مقصد
                <select
                  className={`${inp} mt-1.5`}
                  value={f.target_store_id}
                  onChange={(e) => setF({ ...f, target_store_id: e.target.value })}
                >
                  {choices.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name} ({s.kind === 'main' ? 'اصلی' : 'فروشگاه'})
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label className="text-xs font-bold">
              نام فروشگاه نمایندگی
              <input
                className={`${inp} mt-1.5`}
                maxLength={200}
                value={f.store_name}
                onChange={(e) => setF({ ...f, store_name: e.target.value })}
              />
            </label>
            <label className="text-xs font-bold">
              <span className="flex items-center gap-1.5">
                <Globe size={14} />
                دامنهٔ فروشگاه
              </span>
              <input
                dir="ltr"
                className={`${inp} latin mt-1.5 ${bad.domain ? '!border-danger' : ''}`}
                placeholder="shop.example.com"
                value={f.domain}
                onChange={(e) => setF({ ...f, domain: e.target.value })}
                aria-invalid={!!bad.domain}
              />
              <span className={`mt-1 block text-[11px] font-normal ${bad.domain ? 'text-danger' : 'text-muted'}`}>
                {bad.domain ? 'نام دامنه معتبر نیست.' : 'بدون http و مسیر؛ هر دامنه فقط برای یک فروشگاه ثبت می‌شود.'}
              </span>
            </label>
            <label className="text-xs font-bold">
              <span className="flex items-center gap-1.5">
                <Bot size={14} />
                توکن ربات تلگرام
              </span>
              <span className="relative mt-1.5 block">
                <input
                  dir="ltr"
                  type={show ? 'text' : 'password'}
                  autoComplete="off"
                  spellCheck={false}
                  className={`${inp} latin !pl-11 ${bad.token ? '!border-danger' : ''}`}
                  placeholder="123456789:AA…"
                  value={f.bot_token}
                  onChange={(e) => setF({ ...f, bot_token: e.target.value })}
                  aria-invalid={!!bad.token}
                />
                <button
                  type="button"
                  onClick={() => setShow((x) => !x)}
                  aria-label={show ? 'پنهان‌کردن توکن' : 'نمایش توکن'}
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-muted"
                >
                  {show ? <EyeOff size={17} /> : <Eye size={17} />}
                </button>
              </span>
              <span
                className={`mt-1 block text-[11px] font-normal leading-6 ${bad.token ? 'text-danger' : 'text-muted'}`}
              >
                {bad.token
                  ? 'قالب توکن درست نیست (مثل 123456789:AA…).'
                  : 'از @BotFather با دستور /newbot بساز. توکن رمزنگاری ذخیره می‌شود و بعد از ثبت دیگر نمایش داده نمی‌شود.'}
              </span>
            </label>
            <label className="text-xs font-bold">
              توضیحات و دلیل درخواست نمایندگی (الزامی)
              <textarea
                rows={4}
                maxLength={2000}
                required
                className={`${inp} mt-1.5`}
                value={f.message}
                onChange={(e) => setF({ ...f, message: e.target.value })}
              />
              <span
                className={`mt-1 block text-[11px] font-normal leading-6 ${f.message && !reasonOk ? 'text-danger' : 'text-muted'}`}
              >
                چرا می‌خواهید نماینده شوید؟ سابقهٔ فروش، تعداد مشتری و برنامهٔ خود را بنویسید (حداقل ۲۰ نویسه).
              </span>
            </label>
          </div>
          {err && (
            <p role="alert" className="mt-4 rounded-xl bg-danger-soft p-3 text-sm text-danger">
              {err}
            </p>
          )}
          <button disabled={!ready || busy} onClick={send} className={`${btn} mt-5`}>
            {busy ? 'در حال ثبت…' : 'ارسال درخواست'}
          </button>
        </div>
      )}
      {history.map((a) => (
        <ApplicationCard key={a.id} a={a} onCancel={cancel} onDetails={details} busy={busy} />
      ))}
    </div>
  );
}

const tabs = [
  ['overview', 'نمای کلی', BarChart3],
  ['pricing', 'قیمت‌گذاری', Tags],
  ['customers', 'مشتریان', Users],
  ['accounts', 'اکانت‌های مشتریان', Gauge],
  ['broadcast', 'پیام همگانی', Megaphone],
  ['events', 'مرکز رویداد', BellRing],
  ['payments', 'پرداخت‌ها', CreditCard],
  ['banksms', 'تأیید خودکار بانک', ShieldCheck],
  ['keys', 'کلیدهای API', KeyRound],
  ['hooks', 'وبهوک‌ها', Webhook],
  ['settings', 'تنظیمات فروشگاه', Settings],
];
export default function Reseller({ coreFetch, notify }) {
  const [stores, setStores] = useState(null);
  const [tab, setTab] = useState('overview');
  const pricingDirty = useRef(false); // unsaved price edits: leaving the tab would silently drop them
  const go = (k) => {
    if (
      tab === 'pricing' &&
      k !== 'pricing' &&
      pricingDirty.current &&
      !window.confirm('تغییرات قیمت ذخیره نشده است. بدون ذخیره خارج می‌شوید؟')
    )
      return;
    setTab(k);
  };
  useEffect(() => {
    coreFetch('/api/v1/me/stores')
      .then((r) => (r.ok ? r.json() : []))
      .then(setStores)
      .catch(() => setStores([]));
  }, [coreFetch]);
  const mine = (stores || []).find((s) => s.kind === 'reseller' && s.role === 'owner');
  const base = mine ? `/api/v1/stores/${mine.id}/reseller` : '';
  return (
    <div className="mx-auto max-w-6xl px-5 py-10">
      <PageTitle eyebrow="پنل نماینده" title={mine?.name || 'فروش همکاری'}>
        <a href="#/dashboard" className="btn-soft btn-pill !py-2.5">
          <ArrowRight size={16} />
          حساب من
        </a>
      </PageTitle>
      {stores === null ? (
        <Loading rows={2} />
      ) : !mine ? (
        <Apply coreFetch={coreFetch} notify={notify} stores={stores} />
      ) : (
        <div className="grid gap-8 md:grid-cols-[220px_1fr]">
          <nav
            aria-label="بخش‌های پنل نماینده"
            className="-mx-5 flex gap-2 overflow-x-auto px-5 pb-1 md:sticky md:top-24 md:mx-0 md:h-fit md:flex-col md:gap-1 md:overflow-visible md:px-0"
          >
            {tabs.map(([k, l, Icon]) => (
              <button
                key={k}
                onClick={() => go(k)}
                aria-current={tab === k}
                className={`flex shrink-0 items-center gap-2.5 whitespace-nowrap rounded-xl px-4 py-3 text-sm font-bold transition ${tab === k ? 'bg-primary text-onprimary shadow-soft' : 'text-muted hover:bg-surface2 hover:text-ink'}`}
              >
                <Icon size={18} />
                {l}
              </button>
            ))}
          </nav>
          <section className="min-w-0">
            {tab === 'overview' && <Overview coreFetch={coreFetch} base={base} />}
            {tab === 'pricing' && <Pricing coreFetch={coreFetch} base={base} notify={notify} dirtyRef={pricingDirty} />}
            {tab === 'customers' && <Customers coreFetch={coreFetch} base={base} notify={notify} />}
            {tab === 'accounts' && <OwnerAccounts coreFetch={coreFetch} base={base} notify={notify} />}
            {tab === 'broadcast' && <Broadcast coreFetch={coreFetch} base={base} notify={notify} />}
            {tab === 'events' && <EventCenter coreFetch={coreFetch} base={base} notify={notify} />}
            {tab === 'payments' && <Payments coreFetch={coreFetch} base={base} notify={notify} />}
            {tab === 'banksms' && <BankSms coreFetch={coreFetch} base={base} notify={notify} />}
            {tab === 'keys' && <Keys coreFetch={coreFetch} base={base} notify={notify} />}
            {tab === 'hooks' && <Hooks coreFetch={coreFetch} base={base} notify={notify} />}
            {tab === 'settings' && (
              <div className="space-y-4">
                <Branding coreFetch={coreFetch} base={base} storeId={mine.id} notify={notify} />
                <PayConfig coreFetch={coreFetch} base={base} notify={notify} />
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
