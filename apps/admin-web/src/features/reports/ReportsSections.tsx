import {
  BarChart3,
  Download,
  Lightbulb,
  Percent,
  Receipt,
  RefreshCw,
  Server,
  ShoppingBag,
  Table2,
  UserPlus,
  WalletCards,
} from 'lucide-react';
import { dayShort } from '../../shared/charts.tsx';
import { Funnel, HBars, Legend, SERIES_COLORS, CompareChart, Donut } from './ReportCharts.tsx';
import {
  CHANNEL_LABELS,
  KIND_LABELS,
  METHOD_LABELS,
  PROVIDER_LABELS,
  buildInsights,
  dailyRows,
  fmt,
  fmtBytes,
  fmtPct,
  foldTail,
  nf,
  pick,
} from './reportsLogic.ts';
import type { Json, Toast } from '../../shared/types.ts';
import { RANGES, METRICS, TONES, Seg, Kpi, Card, DataTable, EXPORTS } from './ReportsParts.tsx';
import type { Dispatch, ReactNode, SetStateAction } from 'react';

// Everything the report sections read from ReportsView (state, API payload, derived rows). Each section picks what it needs.
export type ReportModel = {
  days: number;
  setDays: Dispatch<SetStateAction<number>>;
  currency: string;
  setCurrency: Dispatch<SetStateAction<string>>;
  storeId: string;
  setStoreId: Dispatch<SetStateAction<string>>;
  metric: string;
  setMetric: Dispatch<SetStateAction<string>>;
  compare: boolean;
  setCompare: Dispatch<SetStateAction<boolean>>;
  table: boolean;
  setTable: Dispatch<SetStateAction<boolean>>;
  stores: { id: string; name: string }[];
  data: Json;
  err: boolean;
  loading: boolean;
  refresh: () => void;
  exportCsv: (section: string) => void;
  cur: string;
  k: Json;
  s: Json;
  f: Json;
  insights: ReturnType<typeof buildInsights>;
  dim: string;
  mainSeries: { key: string; label: string; values: number[]; color: string; dashed?: boolean; area?: boolean }[];
  unit: string;
  mainTitle: string;
  lead: number[];
  periodTotal: number;
  statusItems: ReturnType<typeof foldTail>;
  split: (
    rows: { key: string; revenue: number }[] | undefined,
    map: Record<string, string>,
  ) => ReturnType<typeof foldTail>;
  total: number;
  productRows: { key: string; label: string; sub?: string; value: number; display?: ReactNode }[];
  storeRows: { key: string; label: string; sub?: string; value: number; display?: ReactNode }[];
  query: string;
  tz: string;
  api: { tick?: number } | undefined;
  toast: Toast;
};

export function ReportsFilters({
  days,
  setDays,
  setCurrency,
  storeId,
  setStoreId,
  stores,
  data,
  loading,
  refresh,
  exportCsv,
  cur,
}: Pick<
  ReportModel,
  | 'days'
  | 'setDays'
  | 'setCurrency'
  | 'storeId'
  | 'setStoreId'
  | 'stores'
  | 'data'
  | 'loading'
  | 'refresh'
  | 'exportCsv'
  | 'cur'
>) {
  return (
    <>
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
            <Seg label="ارز" value={cur} set={setCurrency} items={data.currencies.map((c: string) => [c, c])} />
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
                    (e.currentTarget.closest('details') as HTMLDetailsElement).open = false;
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
    </>
  );
}
export function ReportsKpis({
  data,
  loading,
  cur,
  k,
  dim,
  unit,
}: Pick<ReportModel, 'data' | 'loading' | 'cur' | 'k' | 'dim' | 'unit'>) {
  return (
    <>
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
    </>
  );
}
export function ReportsMainChart({
  days,
  metric,
  setMetric,
  compare,
  setCompare,
  table,
  setTable,
  data,
  cur,
  insights,
  dim,
  mainSeries,
  unit,
  mainTitle,
  periodTotal,
}: Pick<
  ReportModel,
  | 'days'
  | 'metric'
  | 'setMetric'
  | 'compare'
  | 'setCompare'
  | 'table'
  | 'setTable'
  | 'data'
  | 'cur'
  | 'insights'
  | 'dim'
  | 'mainSeries'
  | 'unit'
  | 'mainTitle'
  | 'periodTotal'
>) {
  return (
    <>
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
              rows={dailyRows(data).map((r: Json) => [
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
                    {({ ok: '✓', wn: '!', in: 'i', bd: '✕' } as Record<string, string>)[i.tone]}
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
    </>
  );
}
export function ReportsBreakdowns({
  data,
  cur,
  k,
  dim,
  statusItems,
  split,
  f,
  productRows,
  storeRows,
}: Pick<ReportModel, 'data' | 'cur' | 'k' | 'dim' | 'statusItems' | 'split' | 'f' | 'productRows' | 'storeRows'>) {
  return (
    <>
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
                  center={fmt(items.reduce((a: number, x: { value: number }) => a + x.value, 0))}
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
    </>
  );
}
export function ReportsTables({ data, cur, dim }: Pick<ReportModel, 'data' | 'cur' | 'dim'>) {
  return (
    <>
      <div className={`grid gap-6 lg:grid-cols-[1.2fr_1fr] ${dim}`}>
        <Card title="سلامت روش‌های پرداخت" hint="پرداخت‌های ثبت‌شده در این بازه به تفکیک درگاه">
          {!data ? (
            <div className="skel h-32 w-full" />
          ) : data.payment_providers.length ? (
            <DataTable
              caption="سلامت روش‌های پرداخت"
              cols={['روش', 'موفق', 'ناموفق', 'در انتظار بررسی', `مبلغ (${cur})`, 'نرخ موفقیت']}
              rows={data.payment_providers.map((p: Json) => [
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
    </>
  );
}
