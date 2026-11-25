// Customer › Loyalty club. The club belongs to the store the customer is in: his points, his tier and the rewards HERE.
// Nothing is computed in the browser: Core says what he can take and what is blocked, this screen only shows it.
import { useCallback, useEffect, useState } from 'react';
import { Award, Gift, Sparkles } from 'lucide-react';
import { Empty, Loading, fa, fd } from './ui.tsx';
import { unitOf } from './storeProgram.ts';
import { BLOCKED, TX_KIND, multiplierLabel, tierProgress } from './loyaltyFormat.ts';
import { completeReward, reserveReward } from './loyaltyAttempts.ts';
import { usePendingLoyalty } from './usePendingLoyalty.ts';
import type { Json } from './types';

export default function Loyalty({
  coreFetch,
  storeId,
  accountId,
  notify,
}: {
  coreFetch?: Json;
  storeId?: string;
  accountId?: string;
  notify?: Json;
}) {
  const [d, setD] = useState<Json>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState<Json>(null);
  const pending = usePendingLoyalty(storeId, accountId);

  const load = useCallback(() => {
    return coreFetch(`/api/v1/stores/${storeId}/loyalty`)
      .then((r: Json) => (r.ok ? r.json() : Promise.reject(r)))
      .then((x: Json) => {
        setD(x);
        setFailed(false);
      })
      .catch(() => setFailed(true));
  }, [coreFetch, storeId]);

  useEffect(() => {
    setD(null);
    load();
  }, [load]);

  async function redeem(reward: Json, expectedKey?: string) {
    if (
      busy ||
      !storeId?.trim() ||
      !accountId?.trim() ||
      !pending.ready ||
      typeof reward?.id !== 'string' ||
      !reward.id
    )
      return;
    setBusy(reward.id);
    try {
      let key: string | null;
      try {
        key = await reserveReward(storeId, accountId, reward.id, reward.name || 'پاداش', expectedKey);
      } catch {
        notify('ذخیره امن وضعیت پاداش ممکن نیست؛ درخواست ارسال نشد.');
        return;
      }
      if (!key) {
        notify('وضعیت درخواست قبلی تغییر کرده است؛ پاداش‌ها را دوباره بررسی کنید.');
        return;
      }
      const r = await coreFetch(
        `/api/v1/stores/${encodeURIComponent(storeId)}/loyalty/rewards/${encodeURIComponent(reward.id)}/redeem`,
        {
          method: 'POST',
          headers: { 'Idempotency-Key': key },
        },
      );
      if (r.ok) {
        const result = await r.json();
        if (!result || typeof result.id !== 'string' || !result.id) throw new Error('invalid redemption result');
        try {
          await completeReward(storeId, accountId, reward.id, key);
        } catch {
          // Retaining the key keeps a later retry safe if storage becomes unavailable.
        }
        notify(`«${reward.name}» به کیف پول شما اضافه شد`);
        await load();
      } else {
        const e = await r.json().catch(() => ({}));
        notify(e?.error?.message || 'دریافت پاداش ناموفق بود');
        await load();
      }
    } catch {
      notify('نتیجه درخواست پاداش مشخص نیست؛ همان درخواست را دوباره بررسی کنید.');
    } finally {
      pending.refresh();
      setBusy(null);
    }
  }

  const pendingView = pending.attempts.length > 0 && (
    <div className="space-y-2 rounded-xl border border-line p-3">
      <p className="text-xs text-muted">نتیجه درخواست پاداش قبلی مشخص نیست؛ همان درخواست را پیگیری کنید.</p>
      {pending.attempts.map((attempt) => (
        <button
          key={attempt.key}
          className="btn-primary w-full"
          disabled={busy != null || !pending.ready}
          aria-label={`پیگیری ${attempt.name}`}
          onClick={() => redeem({ id: attempt.rewardId, name: attempt.name }, attempt.key)}
        >
          پیگیری {attempt.name}
        </button>
      ))}
    </div>
  );

  if (!d || !d.enabled) {
    if (pendingView || pending.error) {
      return (
        <div className="card space-y-3">
          {pending.error && <p role="status">بررسی درخواست‌های قبلی ممکن نیست؛ ذخیره‌سازی مرورگر را بررسی کنید.</p>}
          {pendingView}
          {failed && <Empty text="باشگاه مشتریان در دسترس نیست." />}
        </div>
      );
    }
    if (failed) return <Empty text="باشگاه مشتریان در دسترس نیست." />;
    return d ? null : <Loading rows={2} />;
  }

  const unit = unitOf(d.currency);
  const pct = tierProgress(d.tier, d.next_tier, d.lifetime_earned);
  return (
    <div className="card space-y-4" data-testid="loyalty-card">
      <h4 className="flex items-center gap-2 font-extrabold">
        <Award size={18} aria-hidden="true" />
        باشگاه مشتریان
      </h4>
      {(!storeId?.trim() || !accountId?.trim()) && (
        <p role="status" className="text-xs text-muted">
          برای دریافت پاداش، اطلاعات حساب باید بارگذاری شود.
        </p>
      )}
      {pending.error && <p role="status">بررسی درخواست‌های قبلی ممکن نیست؛ ذخیره‌سازی مرورگر را بررسی کنید.</p>}
      {pendingView}

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
          {d.rewards.map((r: Json) => (
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
                disabled={
                  !r.available || busy != null || !pending.ready || pending.attempts.some((a) => a.rewardId === r.id)
                }
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
          {d.history.slice(0, 5).map((t: Json) => (
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
