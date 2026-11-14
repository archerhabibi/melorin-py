import { refundPayment } from './AdminSession.tsx';
import { CircleAlert, Database, Package, ShieldCheck, Ticket, WalletCards, Store } from 'lucide-react';
import Trend from './Trend.tsx';
import { Badge, confirmDialog, label, sid, tone } from './ui.tsx';
import type { Json, Rec, Toast } from './types.ts';

export const money = (v: Json) => new Intl.NumberFormat('fa-IR').format(v || 0);
export const moneyByCurrency = (rows: Json) =>
  (rows || []).map((x: Json) => `${money(x.amount)} ${x.currency}`).join(' · ') || '۰';

const Kpi = ({
  t,
  n,
  s,
  I,
  tint,
  loading,
}: {
  t?: Json;
  n?: Json;
  s?: Json;
  I?: Json;
  tint?: Json;
  loading?: Json;
}) => (
  <div className="card rise p-5">
    <div className="flex items-start justify-between">
      <div className="text-sm text-[var(--mu)]">{t}</div>
      <div className={`rounded-xl p-2.5 ${tint}`}>
        <I size={17} />
      </div>
    </div>
    {loading ? (
      <div className="skel mt-5 h-8 w-2/3" />
    ) : (
      <div className="mt-5 text-2xl font-extrabold tracking-tight">{n}</div>
    )}
    <div className="mt-2 text-xs font-semibold text-[var(--mu)]">{s}</div>
  </div>
);

const QUEUE_LABELS: Record<string, string> = {
  provisioning_failures: 'سفارش‌های ناموفق در تحویل',
  account_discrepancies: 'مغایرت اکانت با پنل',
  panel_orphans: 'اکانت‌های بدون صاحب روی پنل',
  failed_panel_events: 'رویدادهای ناموفق پنل',
  failed_bulk_operations: 'عملیات گروهی ناموفق',
  receipt_reviews: 'رسیدهای در انتظار بررسی',
  refunds_pending: 'استردادهای در انتظار',
  identity_conflicts: 'تعارض هویت',
  reseller_applications: 'درخواست‌های نمایندگی',
  open_tickets: 'تیکت‌های باز',
};

/** Read-only roll-up of what waits for an admin; every row links to the screen of the module that owns the fix. */
function OperationsCenter({ attention, loading }: { attention?: Rec | null; loading?: boolean }) {
  const items: Rec[] = (attention?.items || []).filter((x: Rec) => x.count > 0);
  return (
    <section className="card rise p-5" aria-label="مرکز عملیات">
      <div className="flex items-center justify-between">
        <h3 className="font-extrabold">مرکز عملیات</h3>
        <span className="text-xs text-[var(--mu)]">{money(attention?.total || 0)} مورد در انتظار</span>
      </div>
      {items.length ? (
        <ul className="mt-4 grid gap-2 sm:grid-cols-2">
          {items.map((x) => (
            <li key={x.key}>
              <a
                href={`#/${x.section}`}
                className="flex items-center justify-between rounded-xl border border-[var(--ln)] px-3 py-2 text-sm hover:bg-[var(--mb)]"
              >
                <span>{QUEUE_LABELS[x.key] || x.key}</span>
                <b>{money(x.count)}</b>
              </a>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-4 text-sm text-[var(--mu)]">{loading ? 'در حال دریافت…' : 'موردی در انتظار رسیدگی نیست'}</p>
      )}
    </section>
  );
}

export default function Dashboard({ api, toast }: { api?: Json; toast: Toast }) {
  const summary = api.summary || {};
  const byStatus = [...(summary.orders || [])].sort((a, b) => b.count - a.count);
  const orderCount = byStatus.reduce((a, x) => a + x.count, 0);
  const active = byStatus
    .filter((x) => ['paid', 'processing', 'provisioning'].includes(x.status))
    .reduce((a, x) => a + x.count, 0);
  const needsAttention = byStatus
    .filter((x) => ['manual_review', 'provisioning_failed', 'payment_failed', 'refund_pending'].includes(x.status))
    .reduce((a, x) => a + x.count, 0);
  const openTickets = summary.open_tickets || 0;
  const h = api.health,
    ok = (k: Json) => h?.[k] === 'ok';
  const services = [
    ['Core API', ok('api')],
    ['PostgreSQL', ok('database')],
    ['Redis', ok('redis')],
    ['Worker', ok('worker')],
  ];
  const rows = api.orders || [];
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi
          loading={api.loading}
          t="فروش ثبت‌شده"
          n={moneyByCurrency(summary.payments)}
          s="از گزارش مالی Core"
          I={WalletCards}
          tint="bg-[var(--okb)] text-[var(--ok)]"
        />
        <Kpi
          loading={api.loading}
          t="سفارش‌های فعال"
          n={money(active)}
          s={`${money(orderCount)} کل سفارش`}
          I={Package}
          tint="bg-[var(--inb)] text-[var(--in)]"
        />
        <Kpi
          loading={api.loading}
          t="نیازمند توجه"
          n={money(needsAttention)}
          s="بررسی دستی، خطا یا استرداد"
          I={CircleAlert}
          tint="bg-[var(--wnb)] text-[var(--wn)]"
        />
        <Kpi
          loading={api.loading}
          t="تیکت‌های باز"
          n={money(openTickets)}
          s="از صف پشتیبانی"
          I={Ticket}
          tint="bg-[var(--mb)] text-[var(--tx)]"
        />
      </div>
      <div className="grid gap-6 xl:grid-cols-[1.6fr_.9fr]">
        <div className="space-y-6">
          <Trend tick={api.tick} />
          <OperationsCenter attention={api.attention} loading={api.loading} />
          <section className="card rise p-5">
            <div className="flex items-center justify-between">
              <h3 className="font-extrabold">توزیع وضعیت سفارش‌ها</h3>
              <span className="text-xs text-[var(--mu)]">{money(orderCount)} سفارش</span>
            </div>
            {orderCount ? (
              <>
                <div
                  className="mt-4 flex h-3 overflow-hidden rounded-full bg-[var(--mb)]"
                  role="img"
                  aria-label="نمودار توزیع وضعیت سفارش‌ها"
                >
                  {byStatus.map((x) => (
                    <div
                      key={x.status}
                      title={`${label(x.status)}: ${x.count}`}
                      style={{ width: `${(x.count / orderCount) * 100}%`, background: `var(--${tone(x.status)})` }}
                    />
                  ))}
                </div>
                <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2">
                  {byStatus.map((x) => (
                    <div key={x.status} className="flex items-center gap-2 text-xs">
                      <Badge s={x.status} />
                      <b>{money(x.count)}</b>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <p className="mt-4 text-sm text-[var(--mu)]">{api.loading ? 'در حال دریافت…' : 'هنوز سفارشی ثبت نشده'}</p>
            )}
          </section>
          <section className="card rise overflow-hidden">
            <div className="flex items-center justify-between border-b border-[var(--ln)] px-5 py-4">
              <div>
                <h3 className="font-extrabold">آخرین سفارش‌ها</h3>
                <p className="mt-1 text-xs text-[var(--mu)]">دریافت مستقیم از Core API</p>
              </div>
              <button onClick={api.refresh} className="text-sm font-bold text-[var(--ac)]">
                به‌روزرسانی
              </button>
            </div>
            <div className="overflow-x-auto">
              <table className="tbl min-w-[620px]">
                <thead>
                  <tr>
                    <th>شماره</th>
                    <th>Store</th>
                    <th>مبلغ</th>
                    <th>وضعیت</th>
                    <th>شناسه</th>
                    <th>عملیات</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.length ? (
                    rows.slice(0, 8).map((o: Json) => (
                      <tr key={String(o.id)}>
                        <td className="font-bold">{o.number}</td>
                        <td className="text-[var(--mu)]">{sid(o.store_id)}</td>
                        <td className="font-semibold">
                          {money(o.total)} {o.currency}
                        </td>
                        <td>
                          <Badge s={o.status} />
                        </td>
                        <td className="text-xs text-[var(--mu)]">{sid(o.id)}</td>
                        <td>
                          <button
                            disabled={!o.payment_id || o.payment_status !== 'succeeded'}
                            onClick={async () => {
                              if (
                                !(await confirmDialog('استرداد واقعی این پرداخت انجام شود؟', {
                                  title: 'استرداد پرداخت',
                                  danger: true,
                                  ok: 'استرداد',
                                }))
                              )
                                return;
                              refundPayment(api.base || '', o.payment_id, 'درخواست استرداد توسط Admin')
                                .then(() => {
                                  toast('استرداد ثبت شد');
                                  api.refresh();
                                })
                                .catch(() => toast('استرداد ناموفق بود'));
                            }}
                            className="btn btn-g btn-d"
                          >
                            استرداد
                          </button>
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={6} className="p-12 text-center text-sm text-[var(--mu)]">
                        {api.loading ? 'در حال دریافت…' : 'سفارشی از API برنگشت'}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </div>
        <aside className="space-y-6">
          <section className="rise rounded-2xl bg-[var(--nav)] p-5 text-white">
            <div className="flex items-center justify-between">
              <h3 className="font-extrabold">سلامت زیرساخت</h3>
              <ShieldCheck className="text-[#8ce0ba]" size={20} />
            </div>
            <div className="mt-5 space-y-3.5">
              {services.map(([n, good]) => (
                <div
                  key={String(n)}
                  className="flex items-center justify-between border-b border-white/10 pb-3 last:border-0 last:pb-0"
                >
                  <div className="flex items-center gap-2 text-sm">
                    <span
                      className={`h-2 w-2 rounded-full ${good ? 'bg-[#8ce0ba]' : h ? 'bg-[#f87171]' : 'bg-[#f4c95d]'}`}
                    />
                    {n}
                  </div>
                  <div className="text-xs text-white/70">{good ? 'پایدار' : h ? 'مشکل‌دار' : 'نامشخص'}</div>
                </div>
              ))}
            </div>
          </section>
          <section className="card rise p-5">
            <div className="flex items-center justify-between">
              <h3 className="font-extrabold">آخرین Backup</h3>
              <Database size={19} className="text-[var(--ac)]" />
            </div>
            {api.backups?.[0] ? (
              <div className="mt-4 space-y-2 text-sm">
                <Badge s={api.backups[0].status} />
                <div className="text-xs text-[var(--mu)]">
                  {new Date(api.backups[0].created_at).toLocaleString('fa-IR')}
                </div>
                <div className="text-xs text-[var(--mu)]">{money(api.backups.length)} اجرا ثبت شده</div>
              </div>
            ) : (
              <p className="mt-4 text-sm text-[var(--mu)]">{api.loading ? 'در حال دریافت…' : 'هنوز Backup ثبت نشده'}</p>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}

// Signed-in admin identity (GET /api/v1/me) + sign-out (POST /api/v1/auth/logout revokes the refresh token and clears the cookie).
