import { Lightbulb, Table2 } from 'lucide-react';
import { dayShort } from '../../shared/charts.tsx';
import { Legend } from './ReportCharts.tsx';
import { CompareChart } from './CompareChart.tsx';
import { dailyRows, fmt, nf } from './reportsLogic.ts';
import type { Json } from '../../shared/types.ts';
import { METRICS, TONES, Seg, Card, DataTable } from './ReportsParts.tsx';
import { ReportModel } from './reportModel';

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
