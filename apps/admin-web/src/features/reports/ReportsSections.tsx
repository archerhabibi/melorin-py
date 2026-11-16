import { BarChart3, Download, Percent, Receipt, RefreshCw, ShoppingBag, UserPlus, WalletCards } from 'lucide-react';
import { dayShort } from '../../shared/charts.tsx';
import { SERIES_COLORS } from './ReportCharts.tsx';
import { fmt, fmtPct, nf } from './reportsLogic.ts';
import { RANGES, Seg, Kpi, EXPORTS } from './ReportsParts.tsx';
import { ReportModel } from './reportModel';

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
