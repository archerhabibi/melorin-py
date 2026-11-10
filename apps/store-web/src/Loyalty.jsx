// Customer › Loyalty club. The club belongs to the store the customer is in: his points, his tier and the rewards HERE.
// Nothing is computed in the browser: Core says what he can take and what is blocked, this screen only shows it.
import { useCallback, useEffect, useRef, useState } from 'react';
import { Award, Gift, Sparkles } from 'lucide-react';
import { Empty, Loading, fa, fd } from './ui.jsx';
import { unitOf } from './storeProgram.ts';
import { BLOCKED, TX_KIND, multiplierLabel, tierProgress } from './loyaltyFormat.ts';

const newKey = () =>
  (globalThis.crypto?.randomUUID?.() || `k${Date.now()}${Math.random().toString(16).slice(2)}`).slice(0, 64);

export default function Loyalty({ coreFetch, storeId, notify }) {
  const [d, setD] = useState(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(null);
  // One key per reward until its request finishes, so a double tap or a retry can never spend twice.
  const keys = useRef({});

  const load = useCallback(() => {
    return coreFetch(`/api/v1/stores/${storeId}/loyalty`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r)))
      .then((x) => {
        setD(x);
        setFailed(false);
      })
      .catch(() => setFailed(true));
  }, [coreFetch, storeId]);

  useEffect(() => {
    setD(null);
    load();
  }, [load]);

  async function redeem(reward) {
    if (busy) return;
    setBusy(reward.id);
    keys.current[reward.id] ||= newKey();
    try {
      const r = await coreFetch(`/api/v1/stores/${storeId}/loyalty/rewards/${reward.id}/redeem`, {
        method: 'POST',
        headers: { 'Idempotency-Key': keys.current[reward.id] },
      });
      if (r.ok) {
        delete keys.current[reward.id];
        notify(`«${reward.name}» به کیف پول شما اضافه شد`);
        await load();
      } else {
        delete keys.current[reward.id];
        const e = await r.json().catch(() => ({}));
        notify(e?.error?.message || 'دریافت پاداش ناموفق بود');
        await load();
      }
    } catch {
      // network failure: keep the key, a retry is the same request
      notify('ارتباط برقرار نشد؛ دوباره تلاش کنید');
    } finally {
      setBusy(null);
    }
  }

  if (failed && !d) return <Empty text="باشگاه مشتریان در دسترس نیست." />;
  if (!d) return <Loading rows={2} />;
  if (!d.enabled) return null; // a store without a club shows nothing, not an empty promise

  const unit = unitOf(d.currency);
  const pct = tierProgress(d.tier, d.next_tier, d.lifetime_earned);
  return (
    <div className="card space-y-4" data-testid="loyalty-card">
      <h4 className="flex items-center gap-2 font-extrabold">
        <Award size={18} aria-hidden="true" />
        باشگاه مشتریان
      </h4>

      <div className="grid grid-cols-2 gap-3 text-center">
        <div className="rounded-xl bg-surface2 p-3">
          <div className="text-xl font-extrabold" data-testid="loyalty-balance">
            {fa(d.balance)}
          </div>
          <div className="text-xs text-muted">امتیاز شما</div>
        </div>
        <div className="rounded-xl bg-surface2 p-3">
          <div className="text-xl font-extrabold">{d.tier ? d.tier.name : '—'}</div>
          <div className="text-xs text-muted">
            سطح شما{d.tier ? ` · ضریب ${multiplierLabel(d.tier.multiplier_bp)}` : ''}
          </div>
        </div>
      </div>

      <div>
        <div
          className="h-2 overflow-hidden rounded-full bg-surface2"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct}
          aria-label="پیشرفت تا سطح بعدی"
        >
          <div className="h-full rounded-full bg-[var(--accent,#2563eb)]" style={{ width: `${pct}%` }} />
        </div>
        <p className="mt-2 text-xs text-muted">
          {d.next_tier
            ? `${fa(d.next_tier.points_missing)} امتیاز تا سطح «${d.next_tier.name}»`
            : 'شما در بالاترین سطح هستید.'}
        </p>
      </div>

      {d.debt > 0 && (
        <p className="rounded-xl bg-surface2 p-3 text-xs text-muted" data-testid="loyalty-debt">
          {fa(d.debt)} امتیاز بابت بازگشت وجه از امتیازهای بعدی شما کم می‌شود.
        </p>
      )}

      {d.program?.first_order_bonus > 0 && (
        <p className="flex items-center gap-2 text-xs text-muted">
          <Sparkles size={14} aria-hidden="true" />
          هدیهٔ اولین خرید: {fa(d.program.first_order_bonus)} امتیاز
        </p>
      )}

      {d.rewards?.length > 0 ? (
        <ul className="space-y-2" data-testid="loyalty-rewards">
          {d.rewards.map((r) => (
            <li key={r.id} className="flex items-center justify-between gap-3 rounded-xl border border-line p-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2 font-bold">
                  <Gift size={15} aria-hidden="true" />
                  <span className="truncate">{r.name}</span>
                </div>
                <div className="mt-1 text-xs text-muted">
                  {fa(r.cost_points)} امتیاز ← {fa(r.value)} {unit} اعتبار کیف پول
                  {r.remaining != null ? ` · ${fa(r.remaining)} عدد باقی‌مانده` : ''}
                </div>
                {!r.available && r.blocked_reason && (
                  <div className="mt-1 text-xs text-muted">
                    {BLOCKED[r.blocked_reason] || 'در حال حاضر قابل دریافت نیست'}
                  </div>
                )}
              </div>
              <button
                className="btn-primary shrink-0"
                disabled={!r.available || busy != null}
                onClick={() => redeem(r)}
                aria-label={`دریافت ${r.name}`}
              >
                {busy === r.id ? '...' : 'دریافت'}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted">فعلاً پاداشی تعریف نشده است.</p>
      )}

      {d.history?.length > 0 && (
        <ul className="divide-y divide-[var(--ln)] text-sm" data-testid="loyalty-history">
          {d.history.slice(0, 5).map((t) => (
            <li key={t.id} className="flex items-center justify-between gap-3 py-2">
              <span>{TX_KIND[t.kind] || t.memo || t.kind}</span>
              <span className="text-xs text-muted">{fd(t.created_at)}</span>
              <b dir="ltr" className="latin">
                {t.amount > 0 ? '+' : ''}
                {fa(t.amount)}
              </b>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
