// Reseller panel › Pricing. The reseller prices every package per sales bundle (بسته فروش) of their own store.
// Design: one scope at a time (store-wide base price, or one pool), a table whose rows show cost → price → profit → state,
// a local draft that is reviewed and saved in ONE request (all or nothing), and quick tools (markup, copy from another pool)
// that only fill the draft. The core remains the authority: it refuses any price below the pool's cost.
import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Copy, Info, Layers, Percent, RotateCcw, Save, Tags, X } from "lucide-react";
import { Empty, Loading, fa } from "./ui.jsx";

const J = { "Content-Type": "application/json" };
const BASE = "base";
const FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹";
const AR_DIGITS = "٠١٢٣٤٥٦٧٨٩";
const digitsOf = (v) => String(v ?? "").replace(/[۰-۹]/g, (d) => FA_DIGITS.indexOf(d)).replace(/[٠-٩]/g, (d) => AR_DIGITS.indexOf(d)).replace(/\D/g, "").slice(0, 13);
const toNum = (v) => { const d = digitsOf(v); return d ? Number(d) : null; };
const grouped = (n) => (n == null ? "" : new Intl.NumberFormat("en-US").format(n));
const unitOf = (c) => ({ IRT: "تومان", IRR: "ریال" }[c] || c || "");
const stepOf = (c) => (c === "IRR" ? 10000 : 1000);
const keyOf = (poolId, productId) => `${poolId || BASE}:${productId}`;
const stateOf = (price, cost) => (!price ? "unset" : price < cost ? "below_cost" : "ok");

const STATE = {
  ok: ["قابل فروش", "bg-mint-soft text-mint", CheckCircle2],
  unset: ["بدون قیمت", "bg-surface2 text-muted", Info],
  below_cost: ["زیر قیمت همکاری", "bg-danger-soft text-danger", AlertTriangle],
};

function StateBadge({ state }) {
  const [label, tone, Icon] = STATE[state];
  return <span className={`badge ${tone}`}><Icon size={13} aria-hidden="true" />{label}</span>;
}

async function readError(r) {
  try { const d = await r.json(); return { message: d?.error?.message || "ذخیره‌سازی ناموفق بود", items: d?.error?.details?.errors || [] }; } catch { return { message: "ذخیره‌سازی ناموفق بود", items: [] }; }
}

function MoneyInput({ value, placeholder, onChange, invalid, label, disabled }) {
  const onKey = (e) => {  // Enter moves down the column, like a spreadsheet
    if (e.key !== "Enter") return;
    e.preventDefault();
    const all = [...e.currentTarget.closest("[data-grid]").querySelectorAll("input[data-money]:not(:disabled)")];
    all[all.indexOf(e.currentTarget) + 1]?.focus();
  };
  return <input data-money inputMode="numeric" dir="ltr" autoComplete="off" disabled={disabled} aria-label={label} aria-invalid={invalid || undefined}
    className={`input latin !py-2.5 text-left ${invalid ? "!border-danger !ring-danger/15" : ""}`} placeholder={placeholder} value={grouped(toNum(value))}
    onChange={(e) => onChange(digitsOf(e.target.value))} onKeyDown={onKey} />;
}

export default function Pricing({ coreFetch, base, notify, dirtyRef }) {
  const [rows, setRows] = useState(null);
  const [failed, setFailed] = useState(false);
  const [scope, setScope] = useState(BASE);
  const [draft, setDraft] = useState({});
  const [errors, setErrors] = useState({});
  const [filter, setFilter] = useState("all");
  const [saving, setSaving] = useState(false);
  const [tool, setTool] = useState({ mode: "percent", amount: "20", only: "unset", round: true, from: "" });

  const load = () => { setFailed(false); coreFetch(`${base}/prices`).then((r) => (r.ok ? r.json() : Promise.reject())).then(setRows).catch(() => { setRows([]); setFailed(true); }); };
  useEffect(load, [base]);

  const pools = useMemo(() => {
    const m = new Map();
    (rows || []).forEach((r) => r.pools.forEach((p) => m.has(p.pool_id) || m.set(p.pool_id, { id: p.pool_id, name: p.pool_name, kind: p.kind_label, open: p.open_for_store })));
    return [...m.values()];
  }, [rows]);
  const currency = rows?.[0]?.currency;
  const unit = unitOf(currency);

  // ----- values: saved vs. draft (a draft entry is the digits typed, "" = cleared)
  const savedOf = (row, sc) => (sc === BASE ? row.customer_price : row.pools.find((p) => p.pool_id === sc)?.price) ?? null;
  const valueOf = (row, sc) => { const k = keyOf(sc, row.product_id); return k in draft ? toNum(draft[k]) : savedOf(row, sc); };
  const baseNow = (row) => valueOf(row, BASE);
  const effectiveIn = (row, poolId) => valueOf(row, poolId) ?? baseNow(row);
  const dirtyKeys = Object.keys(draft).filter((k) => {
    const [sc, pid] = [k.slice(0, k.indexOf(":")), k.slice(k.indexOf(":") + 1)];
    const row = (rows || []).find((r) => r.product_id === pid);
    return row && (toNum(draft[k]) ?? null) !== savedOf(row, sc);
  });
  const dirty = dirtyKeys.length > 0;
  useEffect(() => {
    if (dirtyRef) dirtyRef.current = dirty;
    if (!dirty) return;
    const warn = (e) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  useEffect(() => () => { if (dirtyRef) dirtyRef.current = false; }, []);

  const setCell = (sc, row, digits) => {
    const k = keyOf(sc, row.product_id);
    setDraft((d) => ({ ...d, [k]: digits }));
    setErrors((e) => { if (!(k in e)) return e; const { [k]: _gone, ...rest } = e; return rest; });
  };

  // ----- what to show in this scope
  const scopeRows = useMemo(() => (rows || []).filter((r) => scope === BASE || r.pools.some((p) => p.pool_id === scope)), [rows, scope]);
  const costOf = (row, sc) => (sc === BASE ? row.cost_floor : row.pools.find((p) => p.pool_id === sc)?.cost ?? 0);
  const shownState = (row, sc) => stateOf(sc === BASE ? valueOf(row, BASE) : effectiveIn(row, sc), costOf(row, sc));
  const visible = scopeRows.filter((r) => filter === "all" || shownState(r, scope) !== "ok");

  const tally = (poolId) => {
    const t = { ok: 0, unset: 0, below_cost: 0 };
    (rows || []).forEach((r) => r.pools.forEach((p) => { if (!poolId || p.pool_id === poolId) t[stateOf(effectiveIn(r, p.pool_id), p.cost)] += 1; }));
    return t;
  };
  const total = tally();

  // ----- quick tools: they only fill the draft; nothing is saved until "ذخیره"
  const fill = (compute) => {
    const next = {}; let n = 0;
    visible.forEach((row) => {
      const cost = costOf(row, scope);
      // "only unset" = rows that have no price at all; a pool row that inherits the base price is already sold, never overwrite it silently
      if (tool.only === "unset" && (scope === BASE ? valueOf(row, BASE) : effectiveIn(row, scope))) return;
      const price = compute(row, cost);
      if (price == null || price < cost) return;
      next[keyOf(scope, row.product_id)] = String(price); n += 1;
    });
    setDraft((d) => ({ ...d, ...next }));
    return n;
  };
  const markup = () => {
    const amount = toNum(tool.amount); const step = stepOf(currency);
    if (!amount) return notify("مقدار سود را وارد کنید");
    const n = fill((_row, cost) => { const raw = tool.mode === "percent" ? Math.ceil(cost * (1 + amount / 100)) : cost + amount; return tool.round ? Math.ceil(raw / step) * step : raw; });
    notify(n ? `${fa(n)} قیمت در پیش‌نویس گذاشته شد؛ بعد از بررسی ذخیره کنید` : "ردیفی برای اعمال پیدا نشد");
  };
  const copyFrom = () => {
    if (!tool.from) return;
    let skipped = 0;
    const n = fill((row, cost) => { const price = effectiveIn(row, tool.from); if (price && price < cost) skipped += 1; return price || null; });
    notify(`${fa(n)} قیمت کپی شد${skipped ? ` · ${fa(skipped)} مورد از قیمت همکاری این بسته کمتر بود و رد شد` : ""}`);
  };
  const discard = () => { setDraft({}); setErrors({}); };

  // ----- save everything in one request (all or nothing on the server)
  const save = async () => {
    setSaving(true); setErrors({});
    const items = dirtyKeys.map((k) => { const i = k.indexOf(":"); const sc = k.slice(0, i); return { pool_id: sc === BASE ? null : sc, product_id: k.slice(i + 1), customer_price: toNum(draft[k]) }; });
    try {
      const r = await coreFetch(`${base}/prices/batch`, { method: "POST", headers: J, body: JSON.stringify({ items }) });
      if (r.ok) { const d = await r.json(); setRows(d.prices); setDraft({}); notify(d.changed ? `${fa(d.changed)} قیمت ذخیره شد` : "تغییری برای ذخیره نبود"); }
      else {
        const e = await readError(r);
        setErrors(Object.fromEntries(e.items.map((x) => [keyOf(x.pool_id, x.product_id), x.message])));
        notify(e.message);
      }
    } catch { notify("ارتباط با سرور برقرار نشد"); } finally { setSaving(false); }
  };

  if (rows === null) return <Loading rows={3} />;
  if (failed) return <div className="card text-center"><p className="text-sm text-muted">دریافت لیست قیمت‌ها ناموفق بود.</p><button className="btn-ghost mt-3" onClick={load}><RotateCcw size={14} />تلاش دوباره</button></div>;
  if (!rows.length) return <Empty icon={Tags} text="هنوز پکیجی برای فروش در فروشگاه شما فعال نشده است. وقتی مدیریت پکیج‌ها را برای فروشگاه شما باز کند، همین‌جا قیمت‌گذاری می‌کنید." />;

  const inBase = scope === BASE;
  const activePool = pools.find((p) => p.id === scope);
  const errorCount = Object.keys(errors).length;
  const gridCols = inBase ? "md:grid-cols-[minmax(0,1.5fr)_1fr_1.3fr_1fr]" : "md:grid-cols-[minmax(0,1.5fr)_1fr_1.3fr_1fr_1fr]";

  return <div className={`space-y-4 ${dirty ? "pb-24" : ""}`}>
    <div className="card">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-2xl">
          <h3 className="text-lg font-extrabold">قیمت‌گذاری فروشگاه شما</h3>
          <p className="mt-1.5 text-sm leading-7 text-muted">برای هر بسته جداگانه تعیین کنید مشتری‌های شما چه مبلغی بپردازند. اگر برای یک بسته قیمتی نگذارید، <b className="text-ink">قیمت پایه</b> همان پکیج استفاده می‌شود. پکیجی که قیمت ندارد یا ارزان‌تر از قیمت همکاری باشد به مشتری نمایش داده نمی‌شود.</p>
        </div>
        <div className="grid grid-cols-3 gap-2 text-center text-xs" role="group" aria-label="خلاصهٔ وضعیت قیمت‌ها">
          {[["ok", "قابل فروش", total.ok, "text-mint"], ["unset", "بدون قیمت", total.unset, "text-muted"], ["below_cost", "زیر قیمت همکاری", total.below_cost, "text-danger"]].map(([k, l, n, c]) =>
            <button key={k} onClick={() => { setFilter(k === "ok" ? "all" : "attention"); }} className="rounded-xl bg-surface2 px-3 py-2 transition hover:ring-1 hover:ring-line"><div className={`text-xl font-extrabold ${c}`}>{fa(n)}</div><div className="mt-0.5 text-muted">{l}</div></button>)}
        </div>
      </div>
    </div>

    <div role="tablist" aria-label="دامنهٔ قیمت‌گذاری" className="-mx-5 flex gap-2 overflow-x-auto px-5 pb-1 md:mx-0 md:flex-wrap md:px-0">
      {[{ id: BASE, name: "قیمت پایه", kind: "همهٔ بسته‌ها", open: true }, ...pools].map((p) => {
        const t = p.id === BASE ? null : tally(p.id); const attention = t ? t.unset + t.below_cost : 0; const active = scope === p.id;
        return <button key={p.id} role="tab" aria-selected={active} onClick={() => setScope(p.id)} className={`flex shrink-0 items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-bold transition ${active ? "bg-primary text-onprimary shadow-soft" : "bg-surface text-ink ring-1 ring-line hover:bg-surface2"}`}>
          {p.id === BASE ? <Tags size={16} /> : <Layers size={16} />}{p.name}{p.kind && <span className={`text-[11px] font-semibold ${active ? "opacity-70" : "text-muted"}`}>{p.kind}</span>}
          {attention > 0 && <span className="grid h-5 min-w-5 place-items-center rounded-full bg-accent px-1 text-[11px] font-extrabold text-[#10233f]" title={`${fa(attention)} پکیج نیازمند قیمت`}>{fa(attention)}</span>}
        </button>;
      })}
    </div>

    <div className="card !p-0" data-grid>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line p-4">
        <p className="text-xs leading-6 text-muted">
          {inBase ? "قیمت پایه باید از گران‌ترین قیمت همکاری میان بسته‌ها کمتر نباشد؛ بسته‌ای که قیمت اختصاصی دارد از آن استفاده نمی‌کند." : <>قیمت‌های اختصاصی بسته «{activePool?.name}». خالی‌گذاشتن یعنی استفاده از قیمت پایه.{activePool && !activePool.open && <b className="text-danger"> این بسته برای فروشگاه شما غیرفعال است؛ قیمت ثبت می‌شود ولی تا فعال‌شدن فروخته نمی‌شود.</b>}</>}
        </p>
        <label className="flex items-center gap-2 text-xs font-bold">نمایش
          <select className="input !w-auto !py-1.5 !text-xs" value={filter} onChange={(e) => setFilter(e.target.value)}><option value="all">همهٔ پکیج‌ها</option><option value="attention">فقط نیازمند اقدام</option></select></label>
      </div>

      <details className="border-b border-line px-4 py-3 text-sm">
        <summary className="flex cursor-pointer items-center gap-2 font-bold"><Percent size={15} />قیمت‌گذاری سریع<span className="chev mr-auto text-muted">⌄</span></summary>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <div className="space-y-2 rounded-xl bg-surface2 p-3">
            <div className="text-xs font-bold">سود روی قیمت همکاری</div>
            <div className="flex flex-wrap items-center gap-2">
              <input dir="ltr" inputMode="numeric" aria-label="مقدار سود" className="input latin !w-28 !py-2" value={tool.amount} onChange={(e) => setTool({ ...tool, amount: digitsOf(e.target.value) })} />
              <select className="input !w-auto !py-2 !text-xs" aria-label="نوع سود" value={tool.mode} onChange={(e) => setTool({ ...tool, mode: e.target.value })}><option value="percent">درصد</option><option value="fixed">{unit} ثابت</option></select>
              <select className="input !w-auto !py-2 !text-xs" aria-label="اعمال روی" value={tool.only} onChange={(e) => setTool({ ...tool, only: e.target.value })}><option value="unset">فقط بدون قیمت</option><option value="all">همهٔ ردیف‌های نمایش‌داده‌شده</option></select>
            </div>
            <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={tool.round} onChange={(e) => setTool({ ...tool, round: e.target.checked })} />گرد کردن به بالا ({fa(stepOf(currency))} {unit})</label>
            <button className="btn-ghost" onClick={markup}><Percent size={14} />اعمال روی پیش‌نویس</button>
          </div>
          {!inBase && <div className="space-y-2 rounded-xl bg-surface2 p-3">
            <div className="text-xs font-bold">کپی قیمت از بسته دیگر</div>
            <select className="input !py-2 !text-xs" aria-label="بسته مبدأ" value={tool.from} onChange={(e) => setTool({ ...tool, from: e.target.value })}><option value="">انتخاب بسته…</option>{pools.filter((p) => p.id !== scope).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
            <p className="text-[11px] leading-5 text-muted">قیمتی که کمتر از قیمت همکاری همین بسته باشد کپی نمی‌شود.</p>
            <button className="btn-ghost" disabled={!tool.from} onClick={copyFrom}><Copy size={14} />کپی در پیش‌نویس</button>
          </div>}
        </div>
      </details>

      <div className={`hidden gap-3 px-4 py-2.5 text-xs font-bold text-muted md:grid ${gridCols}`} aria-hidden="true">
        <div>پکیج</div><div>{inBase ? "حداقل مجاز" : "قیمت همکاری"}</div><div>{inBase ? "قیمت پایه" : "قیمت فروش شما"} ({unit})</div>{!inBase && <div>سود شما</div>}<div>وضعیت</div>
      </div>
      <ul>
        {visible.map((row) => {
          const k = keyOf(scope, row.product_id); const cost = costOf(row, scope); const own = valueOf(row, scope);
          const eff = inBase ? own : effectiveIn(row, scope); const st = stateOf(eff, cost);
          const typedLow = own != null && own < cost; const profit = eff ? eff - cost : null;
          const inherited = !inBase && !own && baseNow(row) ? baseNow(row) : null;
          const edited = dirtyKeys.includes(k);
          return <li key={row.product_id} className={`grid gap-x-3 gap-y-2 border-t border-line px-4 py-3 ${gridCols} md:items-center ${edited ? "bg-accent-soft/50" : ""}`}>
            <div className="min-w-0"><div className="font-bold">{row.name}</div><div className="text-xs text-muted">{fa(row.duration_days)} روز · {row.traffic_gb ? `${fa(row.traffic_gb)} گیگ` : "نامحدود"}{!inBase && row.pools.find((p) => p.pool_id === scope)?.listed === false && " · در این بسته پنهان است"}</div></div>
            <div className="flex items-center justify-between text-sm md:block"><span className="text-xs text-muted md:hidden">{inBase ? "حداقل مجاز" : "قیمت همکاری"}</span><span className="font-bold">{fa(cost)}</span></div>
            <div><MoneyInput label={`قیمت ${row.name}`} value={k in draft ? draft[k] : own ?? ""} placeholder={inherited ? `${grouped(inherited)} (قیمت پایه)` : "تعیین نشده"} invalid={typedLow || !!errors[k]} onChange={(d) => setCell(scope, row, d)} />
              {(typedLow || errors[k]) && <p role="alert" className="mt-1 text-[11px] leading-5 text-danger">{errors[k] || `کمتر از قیمت همکاری (${fa(cost)})`}</p>}</div>
            {!inBase && <div className={`flex items-center justify-between text-sm md:block ${profit != null && profit < 0 ? "text-danger" : ""}`}><span className="text-xs text-muted md:hidden">سود شما</span>
              <span className="font-bold">{profit == null ? "—" : <>{fa(profit)} <span className="text-xs font-semibold text-muted">({fa(Math.round((profit / cost) * 100))}٪)</span></>}</span></div>}
            <div className="flex items-center justify-between gap-2"><StateBadge state={st} />
              {(own != null || k in draft) && <button className="grid h-8 w-8 place-items-center rounded-full text-muted transition hover:bg-surface2 hover:text-ink" aria-label={inBase ? "پاک‌کردن قیمت پایه" : "حذف قیمت اختصاصی"} title={inBase ? "پاک‌کردن قیمت پایه" : "حذف قیمت اختصاصی (استفاده از قیمت پایه)"} onClick={() => setCell(scope, row, "")}><X size={15} /></button>}</div>
          </li>;
        })}
        {!visible.length && <li className="border-t border-line p-8 text-center text-sm text-muted">{filter === "all" ? "پکیجی در این بسته فروخته نمی‌شود." : "همهٔ پکیج‌های این بخش قیمت معتبر دارند 🎉"}</li>}
      </ul>
    </div>

    {dirty && <div className="fixed inset-x-4 bottom-4 z-40 mx-auto flex max-w-3xl flex-wrap items-center justify-between gap-3 rounded-2xl bg-hero px-5 py-3 shadow-lift md:bottom-6" role="region" aria-label="ذخیرهٔ تغییرات قیمت">
      <div className="text-sm"><b>{fa(dirtyKeys.length)}</b> تغییر ذخیره‌نشده{errorCount > 0 && <span className="mr-2 text-[#f79680]">· {fa(errorCount)} مورد نامعتبر</span>}</div>
      <div className="flex gap-2"><button className="btn rounded-xl bg-white/10 !py-2 text-white hover:bg-white/20" disabled={saving} onClick={discard}>لغو تغییرات</button>
        <button className="btn-primary !bg-[#f7c85c] !py-2 !text-[#10233f]" disabled={saving} onClick={save}><Save size={16} />{saving ? "در حال ذخیره…" : "ذخیرهٔ همه"}</button></div>
    </div>}
  </div>;
}
