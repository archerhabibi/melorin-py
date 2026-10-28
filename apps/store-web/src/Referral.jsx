// Customer › Invite friends. The programme belongs to the store the customer is in: this store's link, this store's reward,
// his own standing HERE. A customer of another store sees that store's numbers there, never these.
import { useEffect, useState } from 'react';
import { Copy, Gift } from 'lucide-react';
import { Empty, Loading, fa } from './ui.jsx';
import { describePlan, unitOf } from './storeProgram.js';

const KIND = { signup_reward: 'پاداش اولین خرید دوست', commission: 'کمیسیون' };
const STATUS = { credited: 'واریز شد', reversed: 'برگشت‌خورده' };

export default function Referral({ coreFetch, storeId, notify }) {
  const [d, setD] = useState(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    setD(null);
    coreFetch(`/api/v1/stores/${storeId}/referral`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r)))
      .then((x) => live && setD(x))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [coreFetch, storeId]);
  const copy = (t) => navigator.clipboard?.writeText(t).then(() => notify('کپی شد'));
  if (failed) return <Empty text="اطلاعات دعوت دوستان در دسترس نیست." />;
  if (!d) return <Loading rows={2} />;
  const unit = unitOf(d.currency);
  const p = d.program || {};
  const links = [
    ['لینک وب', d.links?.web],
    ['لینک تلگرام', d.links?.telegram],
  ].filter(([, v]) => v);
  return (
    <div className="card space-y-4" data-testid="referral-card">
      <h4 className="flex items-center gap-2 font-extrabold">
        <Gift size={18} aria-hidden="true" />
        دعوت دوستان به این فروشگاه
      </h4>
      {p.enabled ? (
        <ul className="space-y-1 text-sm text-muted">
          {p.signup_reward && (
            <li>
              پاداش اولین خرید دوست شما: <b>{describePlan(p.signup_reward, d.currency)}</b>
            </li>
          )}
          {p.commission && (
            <li>
              کمیسیون خریدهای بعدی او: <b>{describePlan(p.commission, d.currency)}</b>
            </li>
          )}
          <li>پاداش‌ها فقط در کیف پول همین فروشگاه شما واریز می‌شود.</li>
        </ul>
      ) : (
        <p className="text-sm text-muted">این فروشگاه فعلاً پاداش دعوت ندارد؛ لینک شما همچنان ثبت می‌شود.</p>
      )}
      <div>
        <p className="text-sm text-muted">کد دعوت شما:</p>
        <div className="mt-2 flex gap-2">
          <code className="latin flex-1 rounded-xl bg-surface2 p-3 text-center font-bold">
            {d.referral_code || '—'}
          </code>
          <button onClick={() => copy(d.referral_code)} className="btn-primary" aria-label="کپی کد دعوت">
            <Copy size={15} aria-hidden="true" />
          </button>
        </div>
      </div>
      {links.map(([label, url]) => (
        <div key={label}>
          <p className="text-sm text-muted">{label}:</p>
          <div className="mt-2 flex gap-2">
            <code dir="ltr" className="latin min-w-0 flex-1 truncate rounded-xl bg-surface2 p-3 text-xs">
              {url}
            </code>
            <button onClick={() => copy(url)} className="btn-primary" aria-label={`کپی ${label}`}>
              <Copy size={15} aria-hidden="true" />
            </button>
          </div>
        </div>
      ))}
      <div className="grid grid-cols-2 gap-3 text-center">
        <div className="rounded-xl bg-surface2 p-3">
          <div className="text-xl font-extrabold">{fa(d.invited)}</div>
          <div className="text-xs text-muted">دعوت‌شده در این فروشگاه</div>
        </div>
        <div className="rounded-xl bg-surface2 p-3">
          <div className="text-xl font-extrabold">{fa(d.earned)}</div>
          <div className="text-xs text-muted">درآمد شما ({unit})</div>
        </div>
      </div>
      {d.commissions?.length > 0 && (
        <ul className="divide-y divide-[var(--ln)] text-sm">
          {d.commissions.slice(0, 5).map((c) => (
            <li key={c.id} className="flex justify-between gap-3 py-2">
              <span>{KIND[c.kind] || c.kind}</span>
              <span className="text-muted">{STATUS[c.status] || c.status}</span>
              <b>{fa(c.amount - c.offset_amount)}</b>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
