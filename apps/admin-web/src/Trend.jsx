import { useEffect, useMemo, useState } from "react";
import { API_BASE, getJson } from "./api.js";
import { TrendChart } from "./charts.jsx";

const full = new Intl.NumberFormat("fa-IR");
const RANGES = [7, 30, 90];
// Days are bucketed in the admin's own time zone (M6.9); the API falls back to UTC for unknown zones.
const browserZone = () => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"; } catch { return "UTC"; } };
const Seg = ({ items, value, set, label }) => <div role="tablist" aria-label={label} className="inline-flex rounded-lg bg-[var(--mb)] p-0.5">{items.map(([k, t]) => <button key={k} role="tab" aria-selected={value === k} onClick={() => set(k)} className={`rounded-md px-3 py-1 text-xs font-bold transition ${value === k ? "bg-[var(--sf)] text-[var(--tx)] shadow-sm" : "text-[var(--mu)]"}`}>{t}</button>)}</div>;

// Sales / orders trend from GET /api/v1/admin/reports/timeseries (currency-safe: one series per currency).
export default function Trend({ tick }) {
  const [days, setDays] = useState(30);
  const [data, setData] = useState(null);
  const [err, setErr] = useState(false);
  const [metric, setMetric] = useState("sales");
  const [cur, setCur] = useState("");
  useEffect(() => {
    let live = true; setErr(false);
    getJson(API_BASE, `/api/v1/admin/reports/timeseries?days=${days}&tz=${encodeURIComponent(browserZone())}`).then((d) => live && setData(d)).catch(() => live && setErr(true));
    return () => { live = false; };
  }, [days, tick]);
  const series = data?.payments || [];
  const active = series.find((s) => s.currency === cur) || series[0];
  const vals = metric === "sales" ? active?.amounts : data?.orders;
  const total = useMemo(() => (vals || []).reduce((a, b) => a + b, 0), [vals]);
  const peak = useMemo(() => { if (!vals?.length) return null; const m = Math.max(...vals); return m ? data.days[vals.indexOf(m)] : null; }, [vals, data]);
  const unit = metric === "sales" ? active?.currency || "" : "سفارش";
  return <section className="card rise p-5">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h3 className="font-extrabold">روند {metric === "sales" ? "فروش" : "سفارش‌ها"}</h3><p className="mt-1 text-xs text-[var(--mu)]">{metric === "sales" ? `پرداخت‌های موفق، روزانه (${data?.timezone || "UTC"}) و جدا برای هر ارز` : `سفارش‌های پرداخت‌شده در هر روز (${data?.timezone || "UTC"})؛ سفارش‌های لغوشده و ناموفق شمرده نمی‌شوند`}</p></div>
      <div className="flex flex-wrap items-center gap-2">
        <Seg label="معیار" value={metric} set={setMetric} items={[["sales", "فروش"], ["orders", "سفارش"]]} />
        {metric === "sales" && series.length > 1 && <Seg label="ارز" value={active?.currency} set={setCur} items={series.map((s) => [s.currency, s.currency])} />}
        <Seg label="بازه" value={days} set={setDays} items={RANGES.map((d) => [d, `${full.format(d)} روز`])} />
      </div>
    </div>
    {err ? <p className="mt-8 rounded-xl bg-[var(--wnb)] p-4 text-sm font-bold text-[var(--wn)]">دریافت داده نمودار ناموفق بود. مطمئن شوید Core به‌روز است و endpoint گزارش سری زمانی را دارد.</p>
      : !data ? <div className="skel mt-5 h-[230px] w-full" />
      : metric === "sales" && !active ? <p className="mt-8 pb-6 text-center text-sm text-[var(--mu)]">در این بازه پرداخت موفقی ثبت نشده است.</p>
      : <>
        <div className="mt-4 flex flex-wrap gap-x-8 gap-y-1"><div><div className="text-xs text-[var(--mu)]">مجموع بازه</div><div className="text-xl font-extrabold">{full.format(total)} <span className="text-xs font-bold text-[var(--mu)]">{unit}</span></div></div>{peak && <div><div className="text-xs text-[var(--mu)]">بیشترین روز</div><div className="text-sm font-bold">{new Intl.DateTimeFormat("fa-IR-u-ca-persian", { day: "numeric", month: "long" }).format(new Date(`${peak}T12:00:00Z`))}</div></div>}</div>
        <div className="mt-3"><TrendChart days={data.days} values={vals} bars={metric === "orders"} color={metric === "sales" ? "var(--ac)" : "var(--in)"} unit={unit} label={`نمودار ${metric === "sales" ? "فروش" : "سفارش‌ها"} ${full.format(days)} روز اخیر؛ مجموع ${full.format(total)} ${unit}`} /></div>
      </>}
  </section>;
}
