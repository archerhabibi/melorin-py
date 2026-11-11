// باشگاه مشتریان: the loyalty club of ONE store at a time. Admin picks the store (main store included); the earning rule, the
// ladder, the rewards and the numbers all belong to that store. The store id is in the URL, never in a body, and Core decides
// every value; this screen only edits and shows it. A reseller manages his own store's club from his panel with the same API.
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Award, Plus, Save, Trash2 } from 'lucide-react';
import { authFetch } from './api.ts';
import { Empty, Field, Section, errText, num, toEn, useRows } from './kit.tsx';
import type { Json, Rec, Toast } from './types.ts';

const unitOf = (c: Json) => (({ IRT: 'تومان', IRR: 'ریال' }) as Rec)[c] || c || '';
const intOf = (v: Json) => {
  const s = toEn(v).replace(/[,٬\s]/g, '');
  return /^\d+$/.test(s) ? Number(s) : null;
};
const J = { 'Content-Type': 'application/json' };

function Program({ program, currency, onSave }: { program?: Json; currency?: Json; onSave?: Json }) {
  const [f, setF] = useState({
    enabled: !!program.enabled,
    earn_unit: String(program.earn_unit ?? 1000),
    points_per_unit: String(program.points_per_unit ?? 1),
    max_points_per_order: program.max_points_per_order ? String(program.max_points_per_order) : '',
    first_order_bonus: String(program.first_order_bonus ?? 0),
    referral_bonus: String(program.referral_bonus ?? 0),
  });
  const [busy, setBusy] = useState(false);
  const set = (k: Json) => (e: Json) =>
    setF((s) => ({ ...s, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }));
  const body = {
    enabled: f.enabled,
    earn_unit: intOf(f.earn_unit),
    points_per_unit: intOf(f.points_per_unit),
    max_points_per_order: f.max_points_per_order === '' ? null : intOf(f.max_points_per_order),
    first_order_bonus: intOf(f.first_order_bonus),
    referral_bonus: intOf(f.referral_bonus),
  };
  const bad =
    !body.earn_unit ||
    !body.points_per_unit ||
    body.first_order_bonus == null ||
    body.referral_bonus == null ||
    (f.max_points_per_order !== '' && !body.max_points_per_order);
  const fields = [
    ['earn_unit', `به‌ازای هر چند ${unitOf(currency)} خرید`],
    ['points_per_unit', 'چند امتیاز بدهد'],
    ['max_points_per_order', 'سقف امتیاز هر سفارش (اختیاری)'],
    ['first_order_bonus', 'هدیهٔ اولین خرید (امتیاز)'],
    ['referral_bonus', 'هدیهٔ معرف پس از اولین خرید دوستش (امتیاز)'],
  ];
  return (
    <Section
      title="برنامهٔ امتیازدهی"
      hint="امتیاز از مبلغ خالص پرداخت‌شده (بعد از تخفیف) و فقط برای سفارش‌های تکمیل‌شدهٔ همین فروشگاه محاسبه می‌شود."
    >
      <div data-testid="loyalty-program" className="space-y-3">
        <label className="flex items-center gap-2 text-xs font-bold">
          <input type="checkbox" checked={f.enabled} onChange={set('enabled')} /> باشگاه این فروشگاه فعال باشد
        </label>
        <div className="grid gap-3 sm:grid-cols-2">
          {fields.map(([k, label]) => (
            <Field key={k} label={label}>
              <input className="inp" dir="ltr" inputMode="numeric" value={(f as Rec)[k]} onChange={set(k)} />
            </Field>
          ))}
        </div>
        <div className="flex justify-end">
          <button
            className="btn"
            disabled={busy || bad}
            onClick={async () => {
              setBusy(true);
              await onSave(body);
              setBusy(false);
            }}
          >
            <Save size={14} /> ذخیره
          </button>
        </div>
      </div>
    </Section>
  );
}

function Tiers({ tiers, onSave }: { tiers?: Json; onSave?: Json }) {
  const [rows, setRows] = useState(
    tiers.map((t: Json) => ({ name: t.name, min_points: String(t.min_points), mult: String(t.multiplier_bp / 10000) })),
  );
  const [busy, setBusy] = useState(false);
  const upd = (i: Json, k: Json, v: Json) =>
    setRows((r: Json) => r.map((x: Json, j: Json) => (j === i ? { ...x, [k]: v } : x)));
  const parsed = rows.map((r: Json) => ({
    name: r.name.trim(),
    min_points: intOf(r.min_points),
    multiplier_bp: Math.round(Number(toEn(r.mult).replace('٫', '.')) * 10000),
  }));
  const bad = !parsed.length || parsed.some((t: Json) => !t.name || t.min_points == null || !(t.multiplier_bp >= 1));
  return (
    <Section
      title="سطح‌ها"
      hint="سطح اول از صفر شروع می‌شود. سطح مشتری از مجموع امتیازی که تا امروز گرفته تعیین می‌شود و ضریب بالاتر امتیاز خریدهای بعدی را بیشتر می‌کند."
    >
      <div data-testid="loyalty-tiers" className="space-y-3">
        {rows.map((r: Json, i: Json) => (
          <div key={i} className="grid grid-cols-[1fr_1fr_5rem_auto] items-end gap-2">
            <Field label="نام">
              <input className="inp" value={r.name} onChange={(e) => upd(i, 'name', e.target.value)} />
            </Field>
            <Field label="از امتیاز">
              <input
                className="inp"
                dir="ltr"
                inputMode="numeric"
                value={r.min_points}
                onChange={(e) => upd(i, 'min_points', e.target.value)}
              />
            </Field>
            <Field label="ضریب">
              <input
                className="inp"
                dir="ltr"
                inputMode="decimal"
                value={r.mult}
                onChange={(e) => upd(i, 'mult', e.target.value)}
              />
            </Field>
            <button
              className="btn"
              aria-label={`حذف ${r.name || 'سطح'}`}
              disabled={rows.length === 1}
              onClick={() => setRows((x: Json) => x.filter((_: Json, j: Json) => j !== i))}
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
        <div className="flex justify-between">
          <button className="btn" onClick={() => setRows((x: Json) => [...x, { name: '', min_points: '', mult: '1' }])}>
            <Plus size={14} /> سطح جدید
          </button>
          <button
            className="btn"
            disabled={busy || bad}
            onClick={async () => {
              setBusy(true);
              await onSave(parsed);
              setBusy(false);
            }}
          >
            <Save size={14} /> ذخیرهٔ سطح‌ها
          </button>
        </div>
      </div>
    </Section>
  );
}

const EMPTY_REWARD = { name: '', value: '', cost_points: '', stock: '', per_user_limit: '', is_active: true };

function Rewards({ rewards, currency, onSave }: { rewards?: Json; currency?: Json; onSave?: Json }) {
  const [f, setF] = useState(EMPTY_REWARD);
  const [editing, setEditing] = useState<Json>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: Json) => (e: Json) =>
    setF((s) => ({ ...s, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }));
  const body = {
    name: f.name.trim(),
    kind: 'wallet_credit',
    value: intOf(f.value),
    cost_points: intOf(f.cost_points),
    stock: f.stock === '' ? null : intOf(f.stock),
    per_user_limit: f.per_user_limit === '' ? null : intOf(f.per_user_limit),
    is_active: f.is_active,
  };
  const bad =
    !body.name ||
    !body.value ||
    !body.cost_points ||
    (f.stock !== '' && body.stock == null) ||
    (f.per_user_limit !== '' && !body.per_user_limit);
  return (
    <Section
      title="پاداش‌ها"
      hint="پاداش فعلاً اعتبار کیف پول همان فروشگاه است و از حساب هزینهٔ باشگاه همان فروشگاه پرداخت می‌شود."
    >
      <div data-testid="loyalty-rewards-manage" className="space-y-3">
        {rewards.length === 0 ? (
          <p className="text-xs text-[var(--mu)]">هنوز پاداشی ساخته نشده است.</p>
        ) : (
          <ul className="divide-y divide-[var(--ln)] text-xs">
            {rewards.map((r: Json) => (
              <li key={r.id} className="flex items-center justify-between gap-3 py-2">
                <span className="min-w-0 truncate font-bold">
                  {r.name}
                  {!r.is_active && <span className="font-normal text-[var(--mu)]"> (غیرفعال)</span>}
                </span>
                <span className="text-[var(--mu)]">
                  {num(r.cost_points)} امتیاز ← {num(r.value)} {unitOf(currency)} · دریافت‌شده {num(r.redeemed_count)}
                </span>
                <button
                  className="btn"
                  aria-label={`ویرایش ${r.name}`}
                  onClick={() => {
                    setEditing(r.id);
                    setF({
                      name: r.name,
                      value: String(r.value),
                      cost_points: String(r.cost_points),
                      stock: r.stock == null ? '' : String(r.stock),
                      per_user_limit: r.per_user_limit == null ? '' : String(r.per_user_limit),
                      is_active: r.is_active,
                    });
                  }}
                >
                  ویرایش
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <Field label="نام پاداش">
              <input className="inp" value={f.name} onChange={set('name')} />
            </Field>
          </div>
          <Field label="هزینه (امتیاز)">
            <input className="inp" dir="ltr" inputMode="numeric" value={f.cost_points} onChange={set('cost_points')} />
          </Field>
          <Field label={`اعتبار کیف پول (${unitOf(currency)})`}>
            <input className="inp" dir="ltr" inputMode="numeric" value={f.value} onChange={set('value')} />
          </Field>
          <Field label="موجودی (اختیاری)">
            <input className="inp" dir="ltr" inputMode="numeric" value={f.stock} onChange={set('stock')} />
          </Field>
          <Field label="سقف برای هر مشتری (اختیاری)">
            <input
              className="inp"
              dir="ltr"
              inputMode="numeric"
              value={f.per_user_limit}
              onChange={set('per_user_limit')}
            />
          </Field>
        </div>
        <div className="flex items-center justify-between">
          <label className="flex items-center gap-2 text-xs font-bold">
            <input type="checkbox" checked={f.is_active} onChange={set('is_active')} /> فعال
          </label>
          <div className="flex gap-2">
            {editing && (
              <button
                className="btn"
                onClick={() => {
                  setEditing(null);
                  setF(EMPTY_REWARD);
                }}
              >
                انصراف
              </button>
            )}
            <button
              className="btn"
              disabled={busy || bad}
              onClick={async () => {
                setBusy(true);
                const ok = await onSave(editing, body);
                setBusy(false);
                if (ok) {
                  setEditing(null);
                  setF(EMPTY_REWARD);
                }
              }}
            >
              <Save size={14} /> {editing ? 'ذخیرهٔ تغییرات' : 'افزودن پاداش'}
            </button>
          </div>
        </div>
      </div>
    </Section>
  );
}

function Adjust({ onSave }: { onSave?: Json }) {
  const [f, setF] = useState({ user_id: '', delta: '', reason: '' });
  const [busy, setBusy] = useState(false);
  const delta = Number(toEn(f.delta).replace('−', '-'));
  const bad = !f.user_id.trim() || !Number.isInteger(delta) || delta === 0 || !f.reason.trim();
  return (
    <Section
      title="افزودن یا کم‌کردن امتیاز یک مشتری"
      hint="دلیل اجباری است و در ممیزی ثبت می‌شود. امتیاز منفی هم ثبت می‌شود و موجودی هرگز از صفر کمتر نمی‌شود."
    >
      <div data-testid="loyalty-adjust" className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="شناسهٔ مشتری">
            <input
              className="inp"
              dir="ltr"
              value={f.user_id}
              onChange={(e) => setF({ ...f, user_id: e.target.value })}
            />
          </Field>
          <Field label="تغییر امتیاز (مثلاً 100 یا -50)">
            <input
              className="inp"
              dir="ltr"
              inputMode="numeric"
              value={f.delta}
              onChange={(e) => setF({ ...f, delta: e.target.value })}
            />
          </Field>
          <Field label="دلیل">
            <input className="inp" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} />
          </Field>
        </div>
        <div className="flex justify-end">
          <button
            className="btn"
            disabled={busy || bad}
            onClick={async () => {
              setBusy(true);
              const ok = await onSave({ user_id: f.user_id.trim(), delta, reason: f.reason.trim() });
              setBusy(false);
              if (ok) setF({ user_id: '', delta: '', reason: '' });
            }}
          >
            ثبت
          </button>
        </div>
      </div>
    </Section>
  );
}

export default function LoyaltyClubView({ api, toast }: { api?: Json; toast: Toast }) {
  const call = useCallback((p: Json, o = {}) => authFetch(api.base, p, o), [api.base]);
  const stores = useRows(call, '/api/v1/admin/stores');
  const [storeId, setStoreId] = useState('');
  const store = useMemo(() => (stores.rows || []).find((s) => s.id === storeId), [stores.rows, storeId]);
  useEffect(() => {
    if (!storeId && stores.rows?.length) setStoreId((stores.rows.find((s) => s.kind === 'main') || stores.rows[0]).id);
  }, [stores.rows, storeId]);

  const base = `/api/v1/stores/${storeId}/loyalty/manage`;
  const [data, setData] = useState<Json>(null);
  const [failed, setFailed] = useState(false);
  const [rev, setRev] = useState(0);
  const load = useCallback(async () => {
    if (!storeId) return;
    try {
      const [a, b, c] = await Promise.all([call(`${base}/program`), call(`${base}/rewards`), call(`${base}/summary`)]);
      if (!a.ok || !b.ok || !c.ok) throw new Error('load');
      setData({ prog: await a.json(), rewards: await b.json(), sum: await c.json() });
      setFailed(false);
      setRev((n) => n + 1);
    } catch {
      setFailed(true);
    }
  }, [call, base, storeId]);
  useEffect(() => {
    setData(null);
    setFailed(false);
    load();
  }, [load]);

  async function write(path: string, method: Json, payload: Json, okText: Json, failText: Json) {
    const r = await call(`${base}${path}`, { method, headers: J, body: JSON.stringify(payload) });
    if (r.ok) {
      toast(okText);
      load();
      return true;
    }
    toast(await errText(r, failText));
    return false;
  }

  const currency = store?.currency;
  return (
    <div className="space-y-4">
      <Section
        title="باشگاه مشتریان هر فروشگاه"
        hint="هر فروشگاه و نمایندگی باشگاه مستقل دارد: امتیاز، سطح و پاداش از یک فروشگاه به فروشگاه دیگر نمی‌رود."
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
        {data && (
          <>
            <dl className="grid grid-cols-2 gap-3 text-center sm:grid-cols-4">
              {[
                ['اعضا', data.sum.members],
                ['امتیاز در گردش', data.sum.points_outstanding],
                ['امتیاز داده‌شده', data.sum.points_issued],
                [`اعتبار پرداخت‌شده (${unitOf(currency)})`, data.sum.value_paid],
              ].map(([l, v]) => (
                <div key={l} className="rounded-xl bg-[var(--mb)] p-3">
                  <dd className="text-lg font-extrabold">{num(v)}</dd>
                  <dt className="text-[11px] text-[var(--mu)]">{l}</dt>
                </div>
              ))}
            </dl>
            {data.sum.tiers.length > 0 && (
              <p className="text-[11px] text-[var(--mu)]">
                {data.sum.tiers.map((t: Json) => `${t.name}: ${num(t.members)}`).join(' · ')}
              </p>
            )}
          </>
        )}
      </Section>
      {!storeId ? (
        <Empty Icon={Award} title="فروشگاهی نیست" text="ابتدا یک فروشگاه بسازید." />
      ) : failed ? (
        <Empty Icon={Award} title="دریافت باشگاه ناموفق بود" text="دوباره تلاش کنید." />
      ) : !data ? null : (
        <>
          <Program
            key={`p${storeId}:${rev}`}
            program={data.prog.program}
            currency={currency}
            onSave={(b: Json) => write('/program', 'PUT', b, 'برنامهٔ باشگاه ذخیره شد', 'ذخیره ناموفق بود')}
          />
          <Tiers
            key={`t${storeId}:${rev}`}
            tiers={data.prog.tiers.length ? data.prog.tiers : data.prog.default_tiers}
            onSave={(tiers: Json) => write('/tiers', 'PUT', { tiers }, 'سطح‌ها ذخیره شد', 'ذخیرهٔ سطح‌ها ناموفق بود')}
          />
          <Rewards
            key={`r${storeId}:${rev}`}
            rewards={data.rewards}
            currency={currency}
            onSave={(id: Json, b: Json) =>
              write(
                id ? `/rewards/${id}` : '/rewards',
                id ? 'PUT' : 'POST',
                b,
                id ? 'پاداش ویرایش شد' : 'پاداش ساخته شد',
                'ذخیرهٔ پاداش ناموفق بود',
              )
            }
          />
          <Adjust onSave={(b: Json) => write('/adjust', 'POST', b, 'امتیاز ثبت شد', 'ثبت امتیاز ناموفق بود')} />
        </>
      )}
    </div>
  );
}
