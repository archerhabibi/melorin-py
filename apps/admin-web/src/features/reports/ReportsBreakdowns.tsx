import { Server } from 'lucide-react';
import { Funnel, HBars, SERIES_COLORS, Donut } from './ReportCharts.tsx';
import {
  CHANNEL_LABELS,
  KIND_LABELS,
  METHOD_LABELS,
  PROVIDER_LABELS,
  fmt,
  fmtBytes,
  fmtPct,
  pick,
} from './reportsLogic.ts';
import type { Json } from '../../shared/types.ts';
import { Card, DataTable } from './ReportsParts.tsx';
import { ReportModel } from './reportModel';

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
