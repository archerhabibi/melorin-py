// Reseller panel › Loyalty club. The reseller runs the club of HIS store only: earning rule, tier ladder, rewards, and manual
// point adjustments. Core validates everything and the store id is in the URL, so nothing here can touch another store.
import { useCallback, useEffect, useState } from 'react';
import { Award, Plus, Save, Trash2 } from 'lucide-react';
import { Empty, Loading, fa } from './ui.jsx';
import { toInt, unitOf } from './storeProgram.js';
import { multiplierLabel } from './loyaltyFormat.js';

const J = { 'Content-Type': 'application/json' };

async function failure(r, fallback) {
  const d = await r.json().catch(() => ({}));
  return d?.error?.message || fallback;
}

function ProgramCard({ base, program, currency, onChanged, notify }) {
  const [f, setF] = useState({
    enabled: !!program.enabled,
    earn_unit: String(program.earn_unit ?? 1000),
    points_per_unit: String(program.points_per_unit ?? 1),
    max_points_per_order: program.max_points_per_order ? String(program.max_points_per_order) : '',
    first_order_bonus: String(program.first_order_bonus ?? 0),
    referral_bonus: String(program.referral_bonus ?? 0),
  });
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) =>
    setF((s) => ({ ...s, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }));
  const body = {
    enabled: f.enabled,
    earn_unit: toInt(f.earn_unit),
    points_per_unit: toInt(f.points_per_unit),
    max_points_per_order: f.max_points_per_order === '' ? null : toInt(f.max_points_per_order),
    first_order_bonus: toInt(f.first_order_bonus),
    referral_bonus: toInt(f.referral_bonus),
  };
  const bad =
    !body.earn_unit ||
    !body.points_per_unit ||
    body.first_order_bonus == null ||
    body.referral_bonus == null ||
    (f.max_points_per_order !== '' && !body.max_points_per_order);
  async function save() {
    setBusy(true);
    const r = await base.coreFetch(`${base.url}/program`, { method: 'PUT', headers: J, body: JSON.stringify(body) });
    setBusy(false);
    if (r.ok) {
      notify('برنامهٔ باشگاه ذخیره شد');
      onChanged();
    } else notify(await failure(r, 'ذخیره ناموفق بود'));
  }
  const fields = [
    ['earn_unit', `به‌ازای هر چند ${unitOf(currency)} خرید`],
    ['points_per_unit', 'چند امتیاز بگیرد'],
    ['max_points_per_order', 'سقف امتیاز هر سفارش (اختیاری)'],
    ['first_order_bonus', 'هدیهٔ اولین خرید (امتیاز)'],
    ['referral_bonus', 'هدیهٔ معرف وقتی دوستش اولین خرید را کرد (امتیاز)'],
  ];
  return (
    <div className="card space-y-3" data-testid="loyalty-program">
      <label className="flex items-center gap-2 font-bold">
        <input type="checkbox" checked={f.enabled} onChange={set('enabled')} /> باشگاه مشتریان فعال باشد
      </label>
      <div className="grid gap-3 sm:grid-cols-2">
        {fields.map(([k, label]) => (
          <label key={k} className="text-sm">
            {label}
            <input
              className="input latin mt-1 text-left"
              dir="ltr"
              inputMode="numeric"
              value={f[k]}
              onChange={set(k)}
            />
          </label>
        ))}
      </div>
      <div className="flex justify-end">
        <button className="btn-primary" disabled={busy || bad} onClick={save}>
          <Save size={15} aria-hidden="true" /> ذخیره
        </button>
      </div>
    </div>
  );
}

function TiersCard({ base, tiers, onChanged, notify }) {
  const [rows, setRows] = useState(
    tiers.map((t) => ({ name: t.name, min_points: String(t.min_points), mult: String(t.multiplier_bp / 10000) })),
  );
  const [busy, setBusy] = useState(false);
  const upd = (i, k, v) => setRows((r) => r.map((x, j) => (j === i ? { ...x, [k]: v } : x)));
  const parsed = rows.map((r) => ({
    name: r.name.trim(),
    min_points: toInt(r.min_points),
    multiplier_bp: Math.round(Number(String(r.mult).replace('٫', '.')) * 10000),
  }));
  const bad = !parsed.length || parsed.some((t) => !t.name || t.min_points == null || !(t.multiplier_bp >= 1));
  async function save() {
    setBusy(true);
    const r = await base.coreFetch(`${base.url}/tiers`, {
      method: 'PUT',
      headers: J,
      body: JSON.stringify({ tiers: parsed }),
    });
    setBusy(false);
    if (r.ok) {
      notify('سطح‌ها ذخیره شد');
      onChanged();
    } else notify(await failure(r, 'ذخیرهٔ سطح‌ها ناموفق بود'));
  }
  return (
    <div className="card space-y-3" data-testid="loyalty-tiers">
      <h4 className="font-extrabold">سطح‌ها</h4>
      <p className="text-xs text-muted">
        سطح اول از صفر امتیاز شروع می‌شود. سطح مشتری از مجموع امتیازی که تا امروز گرفته تعیین می‌شود و ضریب بالاتر
        امتیاز خریدهای بعدی را بیشتر می‌کند.
      </p>
      {rows.map((r, i) => (
        <div key={i} className="grid grid-cols-[1fr_1fr_5rem_auto] items-end gap-2">
          <label className="text-xs">
            نام
            <input className="input mt-1" value={r.name} onChange={(e) => upd(i, 'name', e.target.value)} />
          </label>
          <label className="text-xs">
            از امتیاز
            <input
              className="input latin mt-1 text-left"
              dir="ltr"
              inputMode="numeric"
              value={r.min_points}
              onChange={(e) => upd(i, 'min_points', e.target.value)}
            />
          </label>
          <label className="text-xs">
            ضریب
            <input
              className="input latin mt-1 text-left"
              dir="ltr"
              inputMode="decimal"
              value={r.mult}
              onChange={(e) => upd(i, 'mult', e.target.value)}
            />
          </label>
          <button
            className="btn-ghost"
            aria-label={`حذف ${r.name || 'سطح'}`}
            disabled={rows.length === 1}
            onClick={() => setRows((x) => x.filter((_, j) => j !== i))}
          >
            <Trash2 size={15} aria-hidden="true" />
          </button>
        </div>
      ))}
      <div className="flex justify-between">
        <button className="btn-ghost" onClick={() => setRows((x) => [...x, { name: '', min_points: '', mult: '1' }])}>
          <Plus size={15} aria-hidden="true" /> سطح جدید
        </button>
        <button className="btn-primary" disabled={busy || bad} onClick={save}>
          <Save size={15} aria-hidden="true" /> ذخیرهٔ سطح‌ها
        </button>
      </div>
    </div>
  );
}

const EMPTY_REWARD = { name: '', value: '', cost_points: '', stock: '', per_user_limit: '', is_active: true };

function RewardsCard({ base, rewards, currency, onChanged, notify }) {
  const [f, setF] = useState(EMPTY_REWARD);
  const [editing, setEditing] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) =>
    setF((s) => ({ ...s, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }));
  const body = {
    name: f.name.trim(),
    kind: 'wallet_credit',
    value: toInt(f.value),
    cost_points: toInt(f.cost_points),
    stock: f.stock === '' ? null : toInt(f.stock),
    per_user_limit: f.per_user_limit === '' ? null : toInt(f.per_user_limit),
    is_active: f.is_active,
  };
  const bad =
    !body.name ||
    !body.value ||
    !body.cost_points ||
    (f.stock !== '' && body.stock == null) ||
    (f.per_user_limit !== '' && !body.per_user_limit);
  async function save() {
    setBusy(true);
    const url = editing ? `${base.url}/rewards/${editing}` : `${base.url}/rewards`;
    const r = await base.coreFetch(url, { method: editing ? 'PUT' : 'POST', headers: J, body: JSON.stringify(body) });
    setBusy(false);
    if (r.ok) {
      notify(editing ? 'پاداش ویرایش شد' : 'پاداش ساخته شد');
      setF(EMPTY_REWARD);
      setEditing(null);
      onChanged();
    } else notify(await failure(r, 'ذخیرهٔ پاداش ناموفق بود'));
  }
  const edit = (r) => {
    setEditing(r.id);
    setF({
      name: r.name,
      value: String(r.value),
      cost_points: String(r.cost_points),
      stock: r.stock == null ? '' : String(r.stock),
      per_user_limit: r.per_user_limit == null ? '' : String(r.per_user_limit),
      is_active: r.is_active,
    });
  };
  return (
    <div className="card space-y-3" data-testid="loyalty-rewards-manage">
      <h4 className="font-extrabold">پاداش‌ها</h4>
      {rewards.length === 0 ? (
        <p className="text-sm text-muted">هنوز پاداشی نساخته‌اید.</p>
      ) : (
        <ul className="divide-y divide-[var(--ln)] text-sm">
          {rewards.map((r) => (
            <li key={r.id} className="flex items-center justify-between gap-3 py-2">
              <span className="min-w-0 truncate">
                {r.name}
                {!r.is_active && <span className="text-muted"> (غیرفعال)</span>}
              </span>
              <span className="text-xs text-muted">
                {fa(r.cost_points)} امتیاز ← {fa(r.value)} {unitOf(currency)} · دریافت‌شده {fa(r.redeemed_count)}
              </span>
              <button className="btn-ghost" onClick={() => edit(r)} aria-label={`ویرایش ${r.name}`}>
                ویرایش
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm sm:col-span-2">
          نام پاداش
          <input className="input mt-1" value={f.name} onChange={set('name')} />
        </label>
        <label className="text-sm">
          هزینه (امتیاز)
          <input
            className="input latin mt-1 text-left"
            dir="ltr"
            inputMode="numeric"
            value={f.cost_points}
            onChange={set('cost_points')}
          />
        </label>
        <label className="text-sm">
          اعتبار کیف پول ({unitOf(currency)})
          <input
            className="input latin mt-1 text-left"
            dir="ltr"
            inputMode="numeric"
            value={f.value}
            onChange={set('value')}
          />
        </label>
        <label className="text-sm">
          موجودی (اختیاری)
          <input
            className="input latin mt-1 text-left"
            dir="ltr"
            inputMode="numeric"
            value={f.stock}
            onChange={set('stock')}
          />
        </label>
        <label className="text-sm">
          سقف برای هر مشتری (اختیاری)
          <input
            className="input latin mt-1 text-left"
            dir="ltr"
            inputMode="numeric"
            value={f.per_user_limit}
            onChange={set('per_user_limit')}
          />
        </label>
      </div>
      <div className="flex items-center justify-between">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={f.is_active} onChange={set('is_active')} /> فعال
        </label>
        <div className="flex gap-2">
          {editing && (
            <button
              className="btn-ghost"
              onClick={() => {
                setEditing(null);
                setF(EMPTY_REWARD);
              }}
            >
              انصراف
            </button>
          )}
          <button className="btn-primary" disabled={busy || bad} onClick={save}>
            <Save size={15} aria-hidden="true" /> {editing ? 'ذخیرهٔ تغییرات' : 'افزودن پاداش'}
          </button>
        </div>
      </div>
    </div>
  );
}

function AdjustCard({ base, onChanged, notify }) {
  const [f, setF] = useState({ user_id: '', delta: '', reason: '' });
  const [busy, setBusy] = useState(false);
  const delta = Number(String(f.delta).replace('−', '-'));
  const bad = !f.user_id.trim() || !Number.isInteger(delta) || delta === 0 || !f.reason.trim();
  async function save() {
    setBusy(true);
    const r = await base.coreFetch(`${base.url}/adjust`, {
      method: 'POST',
      headers: J,
      body: JSON.stringify({ user_id: f.user_id.trim(), delta, reason: f.reason.trim() }),
    });
    setBusy(false);
    if (r.ok) {
      notify('امتیاز ثبت شد');
      setF({ user_id: '', delta: '', reason: '' });
      onChanged();
    } else notify(await failure(r, 'ثبت امتیاز ناموفق بود'));
  }
  return (
    <div className="card space-y-3" data-testid="loyalty-adjust">
      <h4 className="font-extrabold">افزودن یا کم‌کردن امتیاز</h4>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="text-sm">
          شناسهٔ مشتری
          <input
            className="input latin mt-1 text-left"
            dir="ltr"
            value={f.user_id}
            onChange={(e) => setF({ ...f, user_id: e.target.value })}
          />
        </label>
        <label className="text-sm">
          تغییر امتیاز (مثلاً 100 یا -50)
          <input
            className="input latin mt-1 text-left"
            dir="ltr"
            inputMode="numeric"
            value={f.delta}
            onChange={(e) => setF({ ...f, delta: e.target.value })}
          />
        </label>
        <label className="text-sm">
          دلیل (اجباری)
          <input className="input mt-1" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} />
        </label>
      </div>
      <div className="flex justify-end">
        <button className="btn-primary" disabled={busy || bad} onClick={save}>
          ثبت
        </button>
      </div>
    </div>
  );
}

export default function ResellerLoyalty({ coreFetch, storeId, notify, currency }) {
  const [prog, setProg] = useState(null);
  const [rewards, setRewards] = useState(null);
  const [sum, setSum] = useState(null);
  const [failed, setFailed] = useState(false);
  const [rev, setRev] = useState(0);
  const url = `/api/v1/stores/${storeId}/loyalty/manage`;
  const base = { coreFetch, url };
  const load = useCallback(async () => {
    try {
      const [a, b, c] = await Promise.all([
        coreFetch(`${url}/program`),
        coreFetch(`${url}/rewards`),
        coreFetch(`${url}/summary`),
      ]);
      if (!a.ok || !b.ok || !c.ok) throw new Error('load');
      setProg(await a.json());
      setRewards(await b.json());
      setSum(await c.json());
      setRev((n) => n + 1);
    } catch {
      setFailed(true);
    }
  }, [coreFetch, url]);
  useEffect(() => {
    load();
  }, [load]);
  if (failed) return <Empty text="مدیریت باشگاه در دسترس نیست." />;
  if (!prog || !rewards || !sum) return <Loading rows={3} />;
  const tiers = prog.tiers.length ? prog.tiers : prog.default_tiers.map((t) => ({ ...t }));
  return (
    <div className="space-y-4">
      <div className="card">
        <h4 className="flex items-center gap-2 font-extrabold">
          <Award size={18} aria-hidden="true" /> باشگاه مشتریان فروشگاه من
        </h4>
        <p className="mt-2 text-sm text-muted">
          امتیاز و پاداش فقط برای مشتریان همین فروشگاه است و اعتبار پاداش از حساب شما پرداخت می‌شود.
        </p>
        <dl className="mt-4 grid grid-cols-2 gap-3 text-center sm:grid-cols-4">
          {[
            ['اعضا', sum.members],
            ['امتیاز در گردش', sum.points_outstanding],
            ['امتیاز داده‌شده', sum.points_issued],
            [`اعتبار پرداخت‌شده (${unitOf(currency)})`, sum.value_paid],
          ].map(([l, v]) => (
            <div key={l} className="rounded-xl bg-surface2 p-3">
              <dd className="text-lg font-extrabold">{fa(v)}</dd>
              <dt className="text-xs text-muted">{l}</dt>
            </div>
          ))}
        </dl>
        {sum.tiers.length > 0 && (
          <p className="mt-3 text-xs text-muted">{sum.tiers.map((t) => `${t.name}: ${fa(t.members)}`).join(' · ')}</p>
        )}
      </div>
      <ProgramCard
        key={`p${rev}`}
        base={base}
        program={prog.program}
        currency={currency}
        onChanged={load}
        notify={notify}
      />
      <TiersCard key={`t${rev}`} base={base} tiers={tiers} onChanged={load} notify={notify} />
      <RewardsCard key={`r${rev}`} base={base} rewards={rewards} currency={currency} onChanged={load} notify={notify} />
      <AdjustCard base={base} onChanged={load} notify={notify} />
      <p className="text-xs text-muted">
        ضریب فعلی: {tiers.map((t) => `${t.name} ${multiplierLabel(t.multiplier_bp)}`).join(' · ')}
      </p>
    </div>
  );
}
