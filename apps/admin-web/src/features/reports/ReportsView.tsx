import { useCallback, useEffect, useMemo, useState } from 'react';
import { Ticket, Undo2 } from 'lucide-react';
import { API_BASE, getJson } from '../../api/api.ts';
import { Heatmap, SERIES_COLORS } from './ReportCharts.tsx';
import {
  STORE_KIND_LABELS,
  browserZone,
  buildInsights,
  buildQuery,
  fmt,
  fmtPct,
  foldTail,
  pick,
  share,
} from './reportsLogic.ts';
import { label as statusLabel } from '../../shared/ui.tsx';
import type { Json, Toast } from '../../shared/types.ts';
import type { ReportModel } from './reportModel.ts';
import { METRICS, Card, download } from './ReportsParts.tsx';
import { ReportsFilters, ReportsKpis } from './ReportsSections.tsx';
import { ReportsMainChart } from './ReportsMainChart.tsx';
import { ReportsBreakdowns, ReportsTables } from './ReportsBreakdowns.tsx';

export default function ReportsView({ api, toast }: { api?: Json; toast: Toast }) {
  const [days, setDays] = useState(30);
  const [currency, setCurrency] = useState('');
  const [storeId, setStoreId] = useState('');
  const [metric, setMetric] = useState('revenue');
  const [compare, setCompare] = useState(true);
  const [table, setTable] = useState(false);
  const [stores, setStores] = useState<ReportModel['stores']>([]);
  const [data, setData] = useState<Json>(null);
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
  const exportCsv = (section: string) =>
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
    const base: ReportModel['mainSeries'] = (
      {
        revenue: [{ key: 'cur', label: 'این بازه', values: s.revenue, color: SERIES_COLORS[0], area: true }],
        orders: [{ key: 'cur', label: 'این بازه', values: s.orders, color: SERIES_COLORS[0] }],
        cash_in: [{ key: 'cur', label: 'این بازه', values: s.cash_in, color: SERIES_COLORS[2], area: true }],
        new_users: [{ key: 'cur', label: 'این بازه', values: s.new_users, color: SERIES_COLORS[6] }],
        cumulative: [
          { key: 'cur', label: 'فروش تجمعی', values: s.cumulative_revenue, color: SERIES_COLORS[0], area: true },
        ],
      } as Record<string, ReportModel['mainSeries']>
    )[metric];
    if (compare && (metric === 'revenue' || metric === 'orders')) {
      const prev = metric === 'revenue' ? s.revenue_prev : s.orders_prev;
      base.push({ key: 'prev', label: 'بازه‌ی قبلی', values: prev, color: SERIES_COLORS[1], dashed: true });
    }
    return base;
  }, [s, metric, compare]);

  const unit = metric === 'orders' ? 'سفارش' : metric === 'new_users' ? 'نفر' : cur;
  const mainTitle = METRICS.find((m) => m[0] === metric)![1];
  const lead = mainSeries[0]?.values || [];
  const periodTotal =
    metric === 'cumulative' ? lead[lead.length - 1] || 0 : lead.reduce((a: number, b: number) => a + b, 0);

  const statusItems = foldTail(
    (data?.orders_by_status || []).map((x: Json) => ({ key: x.status, label: statusLabel(x.status), value: x.count })),
    6,
  ).map((x: Json, i: number) => ({ ...x, color: SERIES_COLORS[i] }));
  const split = (rows: Json, map: Json) =>
    foldTail(
      (rows || []).map((x: Json) => ({ key: x.key, label: pick(map, x.key), value: x.revenue })),
      5,
    ).map((x: Json, i: number) => ({ ...x, color: SERIES_COLORS[i] }));

  const f = data?.funnel;
  const total = k?.revenue.value || 0;
  const productRows = (data?.top_products || []).map((p: Json) => ({
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
  const storeRows = (data?.top_stores || []).map((st: Json) => ({
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
      <ReportsFilters
        days={days}
        setDays={setDays}
        setCurrency={setCurrency}
        storeId={storeId}
        setStoreId={setStoreId}
        stores={stores}
        data={data}
        loading={loading}
        refresh={refresh}
        exportCsv={exportCsv}
        cur={cur}
      />

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

      <ReportsKpis data={data} loading={loading} cur={cur} k={k} dim={dim} unit={unit} />

      <ReportsMainChart
        days={days}
        metric={metric}
        setMetric={setMetric}
        compare={compare}
        setCompare={setCompare}
        table={table}
        setTable={setTable}
        data={data}
        cur={cur}
        insights={insights}
        dim={dim}
        mainSeries={mainSeries}
        unit={unit}
        mainTitle={mainTitle}
        periodTotal={periodTotal}
      />

      <ReportsBreakdowns
        data={data}
        cur={cur}
        k={k}
        dim={dim}
        statusItems={statusItems}
        split={split}
        f={f}
        productRows={productRows}
        storeRows={storeRows}
      />

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

      <ReportsTables data={data} cur={cur} dim={dim} />

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
