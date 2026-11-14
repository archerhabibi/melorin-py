// Reseller panel › Referral programme. The reseller defines what HIS customers earn by inviting friends into HIS store.
// Two default plans (first purchase of an invited friend, and every later purchase). Core validates and stores them for this
// store only; nothing here can touch another store, and the platform never pays this programme.
import { useCallback, useEffect, useState } from 'react';
import { Gift, Save } from 'lucide-react';
import { Empty, Loading, fa } from './ui.tsx';
import { usePlanForm } from '@melorin/web-kit/referralPlan.js';
import { unitOf } from './storeProgram.ts';
import type { Json } from './types';

const J = { 'Content-Type': 'application/json' };
const KINDS = [
  ['signup_reward', 'پاداش اولین خرید دوست', 'یک‌بار، وقتی دوستِ دعوت‌شده برای اولین بار از فروشگاه شما می‌خرد.'],
  ['commission', 'کمیسیون خریدهای بعدی', 'هر بار که همان دوست دوباره از فروشگاه شما می‌خرد.'],
];

function PlanCard({
  kind,
  title,
  hint,
  rule,
  currency,
  onSave,
}: {
  kind?: Json;
  title?: Json;
  hint?: Json;
  rule?: Json;
  currency?: Json;
  onSave?: Json;
}) {
  const { model, setModel, value, setValue, cap, setCap, active, setActive, bad, canSave, save } = usePlanForm({
    kind,
    rule,
    onSave,
  });
  return (
    <div className="card space-y-3" data-testid={`plan-${kind}`}>
      <div>
        <h4 className="font-extrabold">{title}</h4>
        <p className="mt-1 text-xs text-muted">{hint}</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="text-sm">
          نوع
          <select className="input mt-1" value={model} onChange={(e) => setModel(e.target.value)}>
            <option value="percent">درصد از مبلغ خرید</option>
            <option value="fixed">مبلغ ثابت</option>
          </select>
        </label>
        <label className="text-sm">
          {model === 'percent' ? 'درصد' : `مبلغ (${unitOf(currency)})`}
          <input
            className="input latin mt-1 text-left"
            dir="ltr"
            inputMode="decimal"
            aria-invalid={bad || undefined}
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
        </label>
        <label className="text-sm">
          سقف هر پاداش (اختیاری)
          <input
            className="input latin mt-1 text-left"
            dir="ltr"
            inputMode="numeric"
            value={cap}
            onChange={(e) => setCap(e.target.value)}
          />
        </label>
      </div>
      <div className="flex items-center justify-between">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
          فعال
        </label>
        <button className="btn-primary" disabled={!canSave} onClick={save}>
          <Save size={15} aria-hidden="true" /> ذخیره
        </button>
      </div>
    </div>
  );
}

export default function ResellerReferral({
  coreFetch,
  storeId,
  notify,
  currency,
}: {
  coreFetch?: Json;
  storeId?: Json;
  notify?: Json;
  currency?: Json;
}) {
  const [rules, setRules] = useState<Json>(null);
  const [sum, setSum] = useState<Json>(null);
  const [failed, setFailed] = useState(false);
  const load = useCallback(async () => {
    try {
      const [a, b] = await Promise.all([
        coreFetch(`/api/v1/stores/${storeId}/referral-rules`),
        coreFetch(`/api/v1/stores/${storeId}/referrals/summary`),
      ]);
      if (!a.ok || !b.ok) throw new Error('load');
      setRules(await a.json());
      setSum(await b.json());
    } catch {
      setFailed(true);
    }
  }, [coreFetch, storeId]);
  useEffect(() => {
    load();
  }, [load]);
  async function save(body: Json) {
    const r = await coreFetch(`/api/v1/stores/${storeId}/referral-rules`, {
      method: 'PUT',
      headers: J,
      body: JSON.stringify({ product_id: null, ...body }),
    });
    if (r.ok) {
      notify('طرح ذخیره شد');
      load();
    } else {
      const d = await r.json().catch(() => ({}));
      notify(d?.error?.message || 'ذخیره ناموفق بود');
    }
  }
  if (failed) return <Empty text="برنامهٔ معرفی در دسترس نیست." />;
  if (!rules || !sum) return <Loading rows={3} />;
  const defaults = Object.fromEntries(rules.filter((r: Json) => r.product_id == null).map((r: Json) => [r.kind, r]));
  return (
    <div className="space-y-4">
      <div className="card">
        <h4 className="flex items-center gap-2 font-extrabold">
          <Gift size={18} aria-hidden="true" /> برنامهٔ معرفی فروشگاه من
        </h4>
        <p className="mt-2 text-sm text-muted">
          پاداش فقط به مشتریان همین فروشگاه و از سود شما پرداخت می‌شود؛ هیچ ارتباطی با فروشگاه‌های دیگر ندارد.
        </p>
        <dl className="mt-4 grid grid-cols-2 gap-3 text-center sm:grid-cols-4">
          {[
            ['دعوت‌شده', sum.invited],
            ['معرف فعال', sum.referrers],
            [`پرداخت‌شده (${unitOf(currency)})`, sum.paid_out],
            ['بدهی معرف‌ها', sum.outstanding_clawback],
          ].map(([l, v]) => (
            <div key={l} className="rounded-xl bg-surface2 p-3">
              <dd className="text-lg font-extrabold">{fa(v)}</dd>
              <dt className="text-xs text-muted">{l}</dt>
            </div>
          ))}
        </dl>
      </div>
      {KINDS.map(([kind, title, hint]) => (
        <PlanCard
          key={`${kind}:${defaults[kind]?.id || 'new'}`}
          kind={kind}
          title={title}
          hint={hint}
          rule={defaults[kind]}
          currency={currency}
          onSave={save}
        />
      ))}
    </div>
  );
}
