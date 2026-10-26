// Admin → Reports & charts. One payload from GET /api/v1/admin/reports/analytics drives every card on the screen.
// Currency-safe (one currency at a time), compared with the previous period, exportable, with a table view for accessibility.
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  Download,
  Lightbulb,
  Minus,
  Percent,
  Receipt,
  RefreshCw,
  Server,
  ShoppingBag,
  Table2,
  Ticket,
  Undo2,
  UserPlus,
  WalletCards,
} from 'lucide-react';
import { API_BASE, authFetch, getJson } from './api.js';
import { dayShort } from './charts.jsx';
import { Funnel, HBars, Heatmap, Legend, SERIES_COLORS, Sparkline, CompareChart, Donut } from './ReportCharts.jsx';
import {
  CHANNEL_LABELS,
  KIND_LABELS,
  METHOD_LABELS,
  PROVIDER_LABELS,
  STORE_KIND_LABELS,
  browserZone,
  buildInsights,
  buildQuery,
  dailyRows,
  deltaInfo,
  fmt,
  fmtBytes,
  fmtPct,
  foldTail,
  nf,
  pick,
  share,
} from './reportsLogic.js';
import { label as statusLabel } from './ui.jsx';

const RANGES = [7, 30, 90];
const METRICS = [
  ['revenue', 'فروش'],
  ['orders', 'سفارش'],
  ['cash_in', 'ورودی نقدی'],
  ['new_users', 'کاربر جدید'],
  ['cumulative', 'تجمعی'],
];
const TONES = { ok: 'b-ok', wn: 'b-wn', in: 'b-in', bd: 'b-bd' };

const Seg = ({ items, value, set, label }) => (
  <div role="tablist" aria-label={label} className="inline-flex rounded-lg bg-[var(--mb)] p-0.5">
    {items.map(([k, t]) => (
      <button
        key={k}
        role="tab"
        aria-selected={value === k}
        onClick={() => set(k)}
        className={`rounded-md px-3 py-1 text-xs font-bold transition ${value === k ? 'bg-[var(--sf)] text-[var(--tx)] shadow-xs' : 'text-[var(--mu)]'}`}
      >
        {t}
      </button>
    ))}
  </div>
);

function Delta({ delta, invert }) {
  const d = deltaInfo(delta, { invert });
  const Icon = d.dir === 'up' ? ArrowUpRight : d.dir === 'down' ? ArrowDownRight : Minus;
  const tone = d.good === null ? 'b-mu' : d.good ? 'b-ok' : 'b-bd';
  return (
    <span className={`badge ${tone} gap-1`} title="نسبت به بازه‌ی قبلیِ هم‌اندازه">
      <Icon size={12} aria-hidden="true" />
      {d.text}
    </span>
  );
}

function Kpi({ title, Icon, value, unit, kpi, color, invert, loading, hint }) {
  return (
    <div className="card rise p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="text-sm text-[var(--mu)]">{title}</div>
        <Icon size={16} className="text-[var(--mu)]" aria-hidden="true" />
      </div>
      {loading ? (
        <div className="skel mt-4 h-8 w-2/3" />
      ) : (
        <div className="mt-3 flex items-end justify-between gap-2">
          <div className="min-w-0">
            <div className="truncate text-2xl font-extrabold tracking-tight" title={`${value} ${unit || ''}`}>
              {value}
              {unit && <span className="mr-1 text-xs font-bold text-[var(--mu)]">{unit}</span>}
            </div>
            {hint && <div className="mt-1 text-[11px] text-[var(--mu)]">{hint}</div>}
          </div>
          <Sparkline values={kpi?.spark} color={color} />
        </div>
      )}
      <div className="mt-3 min-h-[22px]">{!loading && kpi && <Delta delta={kpi.delta_pct} invert={invert} />}</div>
    </div>
  );
}

const Card = ({ title, hint, right, children, className = '' }) => (
  <section className={`card rise p-5 ${className}`}>
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h3 className="font-extrabold">{title}</h3>
        {hint && <p className="mt-1 text-xs text-[var(--mu)]">{hint}</p>}
      </div>
      {right}
    </div>
    {children}
  </section>
);

function DataTable({ cols, rows, caption }) {
  return (
    <div className="max-h-[360px] overflow-auto rounded-xl border border-[var(--ln)]">
      <table className="tbl min-w-[520px]">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((c, j) => (
                <td key={j}>{c}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

async function download(path, filename) {
  const r = await authFetch(API_BASE, path);
  if (!r.ok) throw new Error(`export ${r.status}`);
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

const EXPORTS = [
  ['daily', 'روزانه'],
  ['products', 'محصولات'],
  ['stores', 'فروشگاه‌ها'],
  ['methods', 'روش پرداخت'],
];

export default function ReportsView({ api, toast }) {
  const [days, setDays] = useState(30);
  const [currency, setCurrency] = useState('');
  const [storeId, setStoreId] = useState('');
  const [metric, setMetric] = useState('revenue');
  const [compare, setCompare] = useState(true);
  const [table, setTable] = useState(false);
  const [stores, setStores] = useState([]);
  const [data, setData] = useState(null);
  const [err, setErr] = useState(false);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const tz = useMemo(browserZone, []);
  const query = buildQuery({ days, tz, currency, storeId });

  useEffect(() => {
    getJson(API_BASE, '/api/v1/admin/stores')
      .then((x) => setStores(Array.isArray(x) ? x : x.items || []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    let live = true;
    setLoading(true);
    setErr(false);
    getJson(API_BASE, `/api/v1/admin/reports/analytics?${query}`)
      .then((d) => live && setData(d))
      .catch(() => live && setErr(true))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [query, tick, api?.tick]);

  const refresh = useCallback(() => setTick((x) => x + 1), []);
  const exportCsv = (section) =>
    download(
      `/api/v1/admin/reports/analytics.csv?section=${section}&${query}`,
      `melorin-${section}-${days}d.csv`,
    ).catch(() => toast?.('دریافت خروجی ناموفق بود'));

  const cur = data?.currency || '';
  const k = data?.kpis;
  const s = data?.series;
  const insights = useMemo(() => buildInsights(data), [data]);
  const dim = loading && data ? 'opacity-60 transition-opacity' : '';

  const mainSeries = useMemo(() => {
    if (!s) return [];
    const base = {
      revenue: [{ key: 'cur', label: 'این بازه', values: s.revenue, color: SERIES_COLORS[0], area: true }],
      orders: [{ key: 'cur', label: 'این بازه', values: s.orders, color: SERIES_COLORS[0] }],
      cash_in: [{ key: 'cur', label: 'این بازه', values: s.cash_in, color: SERIES_COLORS[2], area: true }],
      new_users: [{ key: 'cur', label: 'این بازه', values: s.new_users, color: SERIES_COLORS[6] }],
      cumulative: [
        { key: 'cur', label: 'فروش تجمعی', values: s.cumulative_revenue, color: SERIES_COLORS[0], area: true },
      ],
    }[metric];
    if (compare && (metric === 'revenue' || metric === 'orders')) {
      const prev = metric === 'revenue' ? s.revenue_prev : s.orders_prev;
      base.push({ key: 'prev', label: 'بازه‌ی قبلی', values: prev, color: SERIES_COLORS[1], dashed: true });
    }
    return base;
  }, [s, metric, compare]);

  const unit = metric === 'orders' ? 'سفارش' : metric === 'new_users' ? 'نفر' : cur;
  const mainTitle = METRICS.find((m) => m[0] === metric)[1];
  const lead = mainSeries[0]?.values || [];
  const periodTotal = metric === 'cumulative' ? lead[lead.length - 1] || 0 : lead.reduce((a, b) => a + b, 0);

  const statusItems = foldTail(
    (data?.orders_by_status || []).map((x) => ({ key: x.status, label: statusLabel(x.status), value: x.count })),
    6,
  ).map((x, i) => ({ ...x, color: SERIES_COLORS[i] }));
  const split = (rows, map) =>
    foldTail(
      (rows || []).map((x) => ({ key: x.key, label: pick(map, x.key), value: x.revenue })),
      5,
    ).map((x, i) => ({ ...x, color: SERIES_COLORS[i] }));

  const f = data?.funnel;
  const total = k?.revenue.value || 0;
  const productRows = (data?.top_products || []).map((p) => ({
    key: p.product_id,
    label: p.name,
    sub: `${fmt(p.count)} فروش`,
    value: p.revenue,
    display: (
      <>
        <bdi>{fmt(p.revenue)}</bdi> <bdi>{cur}</bdi>
      </>
    ),
  }));
  const storeRows = (data?.top_stores || []).map((st) => ({
    key: st.store_id,
    label: st.name,
    sub: pick(STORE_KIND_LABELS, st.kind),
    value: st.revenue,
    display: (
      <>
        <bdi>{fmt(st.revenue)}</bdi> <bdi>{cur}</bdi> · <bdi>{fmtPct(share(st.revenue, total))}</bdi>
      </>
    ),
  }));

  return (
    <div className="rpt space-y-6" aria-busy={loading}>
      <section className="card rise flex flex-wrap items-center justify-between gap-3 p-4">
        <div className="flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-[var(--inb)] text-[var(--in)]">
            <BarChart3 size={20} aria-hidden="true" />
          </span>
          <div>
            <h2 className="font-extrabold">گزارشات و نمودارها</h2>
            <p className="text-xs text-[var(--mu)]">
              {data
                ? `${dayShort(data.period.from)} تا ${dayShort(data.period.to)} · ${data.period.timezone}`
                : 'در حال دریافت…'}
              {' · '}مقایسه با {nf.format(days)} روز قبل از آن
            </p>
          </div>
        </div>
        <div className="no-print flex flex-wrap items-center gap-2">
          <Seg label="بازه" value={days} set={setDays} items={RANGES.map((d) => [d, `${nf.format(d)} روز`])} />
          {data?.currencies?.length > 1 && (
            <Seg label="ارز" value={cur} set={setCurrency} items={data.currencies.map((c) => [c, c])} />
          )}
          <select
            aria-label="فروشگاه"
            className="field !py-1.5 text-xs"
            value={storeId}
            onChange={(e) => setStoreId(e.target.value)}
          >
            <option value="">همه‌ی فروشگاه‌ها</option>
            {stores.map((st) => (
              <option key={st.id} value={st.id}>
                {st.name}
              </option>
            ))}
          </select>
          <button className="btn btn-g" onClick={refresh} aria-label="به‌روزرسانی گزارش" title="به‌روزرسانی">
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
          <details className="relative">
            <summary className="btn cursor-pointer list-none">
              <Download size={15} aria-hidden="true" />
              خروجی CSV
            </summary>
            <div className="card absolute left-0 top-[calc(100%+6px)] z-20 w-40 p-1.5">
              {EXPORTS.map(([sec, t]) => (
                <button
                  key={sec}
                  onClick={(e) => {
                    exportCsv(sec);
                    e.currentTarget.closest('details').open = false;
                  }}
                  className="flex w-full rounded-lg px-3 py-2 text-sm hover:bg-[var(--mb)]"
                >
                  {t}
                </button>
              ))}
            </div>
          </details>
        </div>
      </section>

      {err && !data && (
        <p role="alert" className="rounded-xl bg-[var(--wnb)] p-4 text-sm font-bold text-[var(--wn)]">
          دریافت گزارش ناموفق بود. مطمئن شوید Core به‌روز است و مسیر reports/analytics را دارد.
        </p>
      )}
      {err && data && (
        <p role="alert" className="rounded-xl bg-[var(--wnb)] p-3 text-xs font-bold text-[var(--wn)]">
          به‌روزرسانی ناموفق بود؛ آخرین داده‌ی دریافت‌شده نمایش داده می‌شود.
        </p>
      )}

      <div className={`grid gap-4 sm:grid-cols-2 xl:grid-cols-3 ${dim}`}>
        <Kpi
          title="فروش"
          Icon={WalletCards}
          loading={!data}
          value={fmt(k?.revenue.value)}
          unit={cur}
          kpi={k?.revenue}
          color={SERIES_COLORS[0]}
          hint={`میانگین روزانه ${fmt(data?.highlights.avg_daily_revenue)} ${cur}`}
        />
        <Kpi
          title="سفارش‌های فروخته‌شده"
          Icon={ShoppingBag}
          loading={!data}
          value={fmt(k?.orders_sold.value)}
          kpi={k?.orders_sold}
          color={SERIES_COLORS[0]}
          hint={`${fmt(k?.orders_created.value)} سفارش ثبت‌شده`}
        />
        <Kpi
          title="میانگین ارزش سفارش"
          Icon={Receipt}
          loading={!data}
          value={fmt(k?.avg_order_value.value)}
          unit={cur}
          kpi={k?.avg_order_value}
          color={SERIES_COLORS[1]}
        />
        <Kpi
          title="ورودی نقدی"
          Icon={WalletCards}
          loading={!data}
          value={fmt(k?.cash_in.value)}
          unit={cur}
          kpi={k?.cash_in}
          color={SERIES_COLORS[2]}
          hint="پرداخت‌های موفق کارت/درگاه"
        />
        <Kpi
          title="کاربران جدید"
          Icon={UserPlus}
          loading={!data}
          value={fmt(k?.new_users.value)}
          kpi={k?.new_users}
          color={SERIES_COLORS[6]}
          hint={`${fmt(data?.users_total)} کاربر فعال کل`}
        />
        <Kpi
          title="نرخ تبدیل به پرداخت"
          Icon={Percent}
          loading={!data}
          value={fmtPct(k?.conversion_pct.value)}
          kpi={k?.conversion_pct}
          color={SERIES_COLORS[2]}
          hint="سفارش‌های ثبت‌شده که پرداخت شدند"
        />
      </div>

      <div className={`grid gap-6 xl:grid-cols-[1.7fr_1fr] ${dim}`}>
        <Card
          title={`روند ${mainTitle}`}
          hint="روزانه، به وقت منطقه‌ی زمانی شما؛ فروش = سفارش‌های پرداخت‌شده‌ی لغو/استردادنشده"
          right={
            <div className="no-print flex flex-wrap items-center gap-2">
              <Seg label="معیار" value={metric} set={setMetric} items={METRICS} />
              {(metric === 'revenue' || metric === 'orders') && (
                <label className="flex cursor-pointer items-center gap-1.5 text-xs text-[var(--mu)]">
                  <input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} />
                  بازه‌ی قبلی
                </label>
              )}
              <button className="btn btn-g !py-1 text-xs" aria-pressed={table} onClick={() => setTable((x) => !x)}>
                <Table2 size={14} aria-hidden="true" />
                {table ? 'نمودار' : 'جدول'}
              </button>
            </div>
          }
        >
          {!data ? (
            <div className="skel h-[260px] w-full" />
          ) : table ? (
            <DataTable
              caption="جدول روزانه‌ی گزارش"
              cols={['روز', `فروش (${cur})`, 'سفارش', `ورودی نقدی (${cur})`, 'کاربر جدید']}
              rows={dailyRows(data).map((r) => [
                dayShort(r.day),
                fmt(r.revenue),
                fmt(r.orders),
                fmt(r.cash_in),
                fmt(r.new_users),
              ])}
            />
          ) : (
            <>
              <Legend
                items={mainSeries.map((x) => ({ key: x.key, label: x.label, color: x.color, dashed: x.dashed }))}
              />
              <div className="mt-2">
                <CompareChart
                  days={data.days}
                  series={mainSeries}
                  unit={unit}
                  bars={metric === 'orders' && !compare}
                  label={`نمودار ${mainTitle} ${nf.format(days)} روز اخیر`}
                />
              </div>
              <div className="mt-3 flex flex-wrap gap-x-8 gap-y-1 text-xs text-[var(--mu)]">
                <span>
                  مجموع بازه:{' '}
                  <b className="text-[var(--tx)]">
                    {fmt(periodTotal)} {unit}
                  </b>
                </span>
                {data.highlights.wholesale_cost > 0 && metric === 'revenue' && (
                  <span>
                    بهای تمام‌شده‌ی عمده‌فروشی (نمایندگان):{' '}
                    <b className="text-[var(--tx)]">
                      {fmt(data.highlights.wholesale_cost)} {cur}
                    </b>
                  </span>
                )}
              </div>
            </>
          )}
        </Card>

        <Card
          title="یافته‌های کلیدی"
          hint="خلاصه‌ی خودکار از داده‌های همین بازه"
          right={<Lightbulb size={18} className="text-[var(--mu)]" aria-hidden="true" />}
        >
          {!data ? (
            <div className="skel h-40 w-full" />
          ) : insights.length ? (
            <ul className="space-y-2.5">
              {insights.map((i) => (
                <li key={i.id} className="flex gap-2.5 text-sm leading-6">
                  <span className={`badge ${TONES[i.tone]} mt-0.5 h-5 shrink-0 px-1.5`} aria-hidden="true">
                    {{ ok: '✓', wn: '!', in: 'i', bd: '✕' }[i.tone]}
                  </span>
                  <span>{i.text}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="py-8 text-center text-sm text-[var(--mu)]">برای ساخت یافته‌ها داده‌ی بیشتری لازم است.</p>
          )}
        </Card>
      </div>

      <div className={`grid gap-6 lg:grid-cols-2 ${dim}`}>
        <Card title="قیف فروش" hint="سفارش‌های ثبت‌شده در این بازه و مسیر آن‌ها تا تحویل">
          {!f ? (
            <div className="skel h-40 w-full" />
          ) : (
            <>
              <Funnel
                stages={[
                  { key: 'created', label: 'ثبت‌شده', value: f.created },
                  { key: 'paid', label: 'پرداخت‌شده', value: f.paid },
                  { key: 'completed', label: 'تحویل‌شده', value: f.completed },
                ]}
              />
              <div className="mt-4 flex flex-wrap gap-2 text-xs">
                <span className="badge b-bd">ناموفق: {fmt(f.failed)}</span>
                <span className="badge b-mu">لغوشده: {fmt(f.cancelled)}</span>
                <span className="badge b-wn">
                  استرداد: {fmt(k.refunds.count)} ({fmtPct(k.refunds.rate_pct)})
                </span>
                <span className="badge b-ok">موفقیت تحویل: {fmtPct(f.provisioning_success_pct)}</span>
              </div>
            </>
          )}
        </Card>
        <Card title="وضعیت سفارش‌ها" hint="سفارش‌های ثبت‌شده در این بازه">
          {!data ? (
            <div className="skel h-40 w-full" />
          ) : statusItems.length ? (
            <Donut items={statusItems} center={fmt(f.created)} sub="سفارش" label="نمودار دونات وضعیت سفارش‌ها" />
          ) : (
            <p className="py-10 text-center text-sm text-[var(--mu)]">سفارشی در این بازه ثبت نشده.</p>
          )}
        </Card>
      </div>

      <div className={`grid gap-6 lg:grid-cols-3 ${dim}`}>
        {[
          ['روش پرداخت', 'سهم از فروش', data?.by_method, METHOD_LABELS],
          ['کانال فروش', 'سهم از فروش', data?.by_channel, CHANNEL_LABELS],
          ['نوع سفارش', 'سهم از فروش', data?.by_kind, KIND_LABELS],
        ].map(([t, h, rows, map]) => {
          const items = split(rows, map);
          return (
            <Card key={t} title={t} hint={h}>
              {!data ? (
                <div className="skel h-32 w-full" />
              ) : items.length ? (
                <Donut
                  stack
                  items={items}
                  size={130}
                  center={fmt(items.reduce((a, x) => a + x.value, 0))}
                  sub={cur}
                  label={`نمودار ${t}`}
                />
              ) : (
                <p className="py-8 text-center text-sm text-[var(--mu)]">فروشی ثبت نشده.</p>
              )}
            </Card>
          );
        })}
      </div>

      <div className={`grid gap-6 lg:grid-cols-2 ${dim}`}>
        <Card title="پرفروش‌ترین محصولات" hint={`بر اساس فروش (${cur})`}>
          {!data ? (
            <div className="skel h-40 w-full" />
          ) : (
            <HBars rows={productRows} color={SERIES_COLORS[0]} empty="فروشی ثبت نشده" />
          )}
        </Card>
        <Card title="فروشگاه‌ها و نمایندگان" hint={`سهم هر فروشگاه از فروش (${cur})`}>
          {!data ? (
            <div className="skel h-40 w-full" />
          ) : (
            <HBars rows={storeRows} color={SERIES_COLORS[0]} empty="فروشی ثبت نشده" />
          )}
        </Card>
      </div>

      <Card
        title="زمان‌های اوج فروش"
        hint="تعداد سفارش‌های فروخته‌شده به تفکیک روز هفته و ساعت (به وقت شما)"
        className={dim}
      >
        {!data ? (
          <div className="skel h-48 w-full" />
        ) : (
          <Heatmap matrix={data.heatmap.weekday_hour} peak={data.heatmap.peak} />
        )}
      </Card>

      <div className={`grid gap-6 lg:grid-cols-[1.2fr_1fr] ${dim}`}>
        <Card title="سلامت روش‌های پرداخت" hint="پرداخت‌های ثبت‌شده در این بازه به تفکیک درگاه">
          {!data ? (
            <div className="skel h-32 w-full" />
          ) : data.payment_providers.length ? (
            <DataTable
              caption="سلامت روش‌های پرداخت"
              cols={['روش', 'موفق', 'ناموفق', 'در انتظار بررسی', `مبلغ (${cur})`, 'نرخ موفقیت']}
              rows={data.payment_providers.map((p) => [
                pick(PROVIDER_LABELS, p.provider),
                fmt(p.succeeded),
                fmt(p.failed),
                fmt(p.awaiting_review),
                fmt(p.amount),
                fmtPct(p.success_rate),
              ])}
            />
          ) : (
            <p className="py-8 text-center text-sm text-[var(--mu)]">پرداختی در این بازه ثبت نشده.</p>
          )}
        </Card>
        <Card
          title="وضعیت عملیاتی اکنون"
          hint="لحظه‌ای؛ به بازه و فروشگاه انتخابی وابسته نیست"
          right={<Server size={18} className="text-[var(--mu)]" aria-hidden="true" />}
        >
          {!data ? (
            <div className="skel h-32 w-full" />
          ) : (
            <dl className="grid grid-cols-2 gap-3 text-sm">
              {[
                ['اکانت فعال', fmt(data.vpn.active)],
                ['انقضا تا ۷ روز', fmt(data.vpn.expiring_7d)],
                [
                  'مصرف ترافیک فعال‌ها',
                  `${fmtBytes(data.vpn.traffic_used_bytes)}${data.vpn.traffic_limit_bytes ? ` از ${fmtBytes(data.vpn.traffic_limit_bytes)}` : ''}`,
                ],
                ['تیکت باز', fmt(data.tickets.open)],
                ['سفارش نیازمند توجه', fmt(data.attention_orders)],
                ['کاربر فعال', fmt(data.users_total)],
              ].map(([t, v]) => (
                <div key={t} className="rounded-xl bg-[var(--mb)] p-3">
                  <dt className="text-xs text-[var(--mu)]">{t}</dt>
                  <dd className="mt-1 font-extrabold">{v}</dd>
                </div>
              ))}
            </dl>
          )}
        </Card>
      </div>

      <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-[var(--mu)]">
        <span>
          <Undo2 size={11} className="ml-1 inline" aria-hidden="true" />
          مبالغ هیچ‌گاه بین ارزهای مختلف جمع نمی‌شوند؛ گزارش فقط برای ارز انتخاب‌شده است.
        </span>
        <span>
          <Ticket size={11} className="ml-1 inline" aria-hidden="true" />
          «کاربران جدید» و «وضعیت عملیاتی» به انتخاب فروشگاه وابسته نیستند.
        </span>
      </p>
    </div>
  );
}
