// برنامه‌های معرفی: the referral programme of ONE store at a time. Admin picks the store; the plans, the numbers and the
// saved rules all belong to that store (Core never mixes stores). A reseller may also edit his own store's plans from his panel.
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Gift, Save } from 'lucide-react';
import { authFetch } from './api.js';
import { Empty, Field, Section, errText, num, toEn, useRows } from './kit.jsx';

const KINDS = [
  ['signup_reward', 'پاداش اولین خرید معرفی‌شده', 'یک‌بار، در اولین خرید مشتریِ دعوت‌شده در همین فروشگاه.'],
  ['commission', 'کمیسیون خریدهای بعدی', 'هر خرید بعدیِ همان مشتری در همین فروشگاه.'],
];
const unitOf = (c) => ({ IRT: 'تومان', IRR: 'ریال' })[c] || c || '';
const intOf = (v) => (/^\d+$/.test(toEn(v).replace(/[,٬\s]/g, '')) ? Number(toEn(v).replace(/[,٬\s]/g, '')) : null);
const bpOf = (v) => {
  const s = toEn(v).replace('٫', '.').trim();
  return /^\d+(\.\d{1,2})?$/.test(s) ? Math.round(Number(s) * 100) : null;
};

function Plan({ kind, title, hint, rule, currency, onSave }) {
  const [model, setModel] = useState(rule?.model || 'percent');
  const [value, setValue] = useState(rule ? String(rule.model === 'percent' ? rule.value / 100 : rule.value) : '');
  const [cap, setCap] = useState(rule?.max_amount ? String(rule.max_amount) : '');
  const [active, setActive] = useState(rule ? rule.is_active : true);
  const [busy, setBusy] = useState(false);
  const v = model === 'percent' ? bpOf(value) : intOf(value);
  const bad = value !== '' && (v == null || (cap !== '' && intOf(cap) == null));
  async function save() {
    if (v == null || bad) return;
    setBusy(true);
    await onSave({ kind, model, value: v, max_amount: cap ? intOf(cap) : null, is_active: active });
    setBusy(false);
  }
  return (
    <Section title={title} hint={hint}>
      <div className="grid gap-3 sm:grid-cols-3" data-testid={`plan-${kind}`}>
        <Field label="نوع">
          <select className="inp" value={model} onChange={(e) => setModel(e.target.value)}>
            <option value="percent">درصد از مبلغ خرید</option>
            <option value="fixed">مبلغ ثابت</option>
          </select>
        </Field>
        <Field
          label={model === 'percent' ? 'درصد' : `مبلغ (${unitOf(currency)})`}
          error={bad ? 'مقدار نامعتبر است' : null}
        >
          <input
            className="inp"
            dir="ltr"
            inputMode="decimal"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
        </Field>
        <Field label="سقف هر پاداش (اختیاری)">
          <input className="inp" dir="ltr" inputMode="numeric" value={cap} onChange={(e) => setCap(e.target.value)} />
        </Field>
      </div>
      <div className="flex items-center justify-between">
        <label className="flex items-center gap-2 text-xs font-bold">
          <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> فعال
        </label>
        <button className="btn" disabled={busy || bad || value === ''} onClick={save}>
          <Save size={14} /> ذخیره
        </button>
      </div>
    </Section>
  );
}

export default function ReferralProgramsView({ api, toast }) {
  const call = useCallback((p, o = {}) => authFetch(api.base, p, o), [api.base]);
  const stores = useRows(call, '/api/v1/admin/stores');
  const [storeId, setStoreId] = useState('');
  const store = useMemo(() => (stores.rows || []).find((s) => s.id === storeId), [stores.rows, storeId]);
  useEffect(() => {
    if (!storeId && stores.rows?.length) setStoreId((stores.rows.find((s) => s.kind === 'main') || stores.rows[0]).id);
  }, [stores.rows, storeId]);
  const rules = useRows(call, storeId ? `/api/v1/admin/referral-rules?store_id=${storeId}` : '', { skip: !storeId });
  const [sum, setSum] = useState(null);
  const loadSum = useCallback(async () => {
    if (!storeId) return;
    try {
      const r = await call(`/api/v1/admin/stores/${storeId}/referrals/summary`);
      setSum(r.ok ? await r.json() : null);
    } catch {
      setSum(null);
    }
  }, [call, storeId]);
  useEffect(() => {
    setSum(null);
    loadSum();
  }, [loadSum]);
  async function save(body) {
    const r = await call('/api/v1/admin/referral-rules', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ product_id: null, store_id: storeId, ...body }),
    });
    if (r.ok) {
      toast('طرح ذخیره شد');
      rules.load();
      loadSum();
    } else toast(await errText(r, 'ذخیره ناموفق بود'));
  }
  const defaults = Object.fromEntries((rules.rows || []).filter((r) => r.product_id == null).map((r) => [r.kind, r]));
  const currency = store?.currency;
  return (
    <div className="space-y-4">
      <Section
        title="برنامهٔ معرفی هر فروشگاه"
        hint="هر فروشگاه و نمایندگی برنامهٔ مستقل دارد: لینک، طرح، کیف پول و هزینهٔ پاداش از همان فروشگاه است."
      >
        <Field label="فروشگاه">
          <select className="inp" value={storeId} onChange={(e) => setStoreId(e.target.value)} aria-label="فروشگاه">
            {(stores.rows || []).map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} {s.kind === 'main' ? '(اصلی)' : '(نمایندگی)'}
              </option>
            ))}
          </select>
        </Field>
        {sum && (
          <dl className="grid grid-cols-2 gap-3 text-center sm:grid-cols-4">
            {[
              ['دعوت‌شده', sum.invited],
              ['معرف فعال', sum.referrers],
              [`پرداخت‌شده (${unitOf(currency)})`, sum.paid_out],
              ['بدهی معرف‌ها', sum.outstanding_clawback],
            ].map(([l, v]) => (
              <div key={l} className="rounded-xl bg-[var(--mb)] p-3">
                <dd className="text-lg font-extrabold">{num(v)}</dd>
                <dt className="text-[11px] text-[var(--mu)]">{l}</dt>
              </div>
            ))}
          </dl>
        )}
      </Section>
      {!storeId ? (
        <Empty Icon={Gift} title="فروشگاهی نیست" text="ابتدا یک فروشگاه بسازید." />
      ) : rules.failed ? (
        <Empty Icon={Gift} title="دریافت طرح‌ها ناموفق بود" text="دوباره تلاش کنید." />
      ) : (
        KINDS.map(([kind, title, hint]) => (
          <Plan
            key={`${storeId}:${kind}:${defaults[kind]?.id || 'new'}`}
            kind={kind}
            title={title}
            hint={hint}
            rule={defaults[kind]}
            currency={currency}
            onSave={save}
          />
        ))
      )}
    </div>
  );
}
