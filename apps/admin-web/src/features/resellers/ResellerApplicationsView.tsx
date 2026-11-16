import { useMemo, useState } from 'react';
import { CheckCircle2, Clock, Globe, ShieldQuestion, Store, UserPlus, XCircle } from 'lucide-react';
import { useCall } from '../../api/api.ts';
import { Badge, dt } from '../../shared/ui.tsx';
import { Empty, ErrorBar, KpiBar, Pills, SearchBox, Stat, useRows } from '../../shared/kit.tsx';
import type { Json, Toast } from '../../shared/types.ts';
import { BotCell, ReviewDrawer } from './ResellerReviewDrawer';

const STATUS_PILLS = [
  ['pending', 'در انتظار'],
  ['awaiting_details', 'منتظر دامنه و توکن'],
  ['approved', 'تأیید‌شده'],
  ['rejected', 'رد‌شده'],
  ['cancelled', 'لغو‌شده'],
  ['all', 'همه'],
];

export default function ResellerApplicationsView({ api, toast }: { api?: Json; toast: Toast }) {
  const call = useCall(api);
  const { rows, failed, load } = useRows(call, '/api/v1/admin/reseller-applications');
  const [filter, setFilter] = useState('pending');
  const [q, setQ] = useState('');
  const [open, setOpen] = useState<Json>(null);

  // eslint-disable-next-line react-hooks/exhaustive-deps -- T-W08: reviewed, dependency list intentionally limited (adding the flagged value risks refetch loops); verify in a browser before changing
  const all = rows || [];
  const count = (s: Json) => (s === 'all' ? all.length : all.filter((x) => x.status === s).length);
  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    return all.filter(
      (x) =>
        (filter === 'all' || x.status === filter) &&
        (!t ||
          [x.store_name, x.domain, x.user_email, x.user_name, x.bot_username].some((v) =>
            (v || '').toLowerCase().includes(t),
          )),
    );
  }, [all, filter, q]);
  const unverified = all.filter((x) => x.status === 'pending' && !x.bot_verified).length;

  return (
    <div className="space-y-5">
      <KpiBar cols={4}>
        <Stat
          label="در انتظار بررسی"
          value={count('pending')}
          tone="wn"
          Icon={Clock}
          active={filter === 'pending'}
          onClick={() => setFilter('pending')}
        />
        <Stat
          label="تأیید‌شده"
          value={count('approved')}
          tone="ok"
          Icon={CheckCircle2}
          active={filter === 'approved'}
          onClick={() => setFilter('approved')}
        />
        <Stat
          label="رد‌شده"
          value={count('rejected')}
          tone="bd"
          Icon={XCircle}
          active={filter === 'rejected'}
          onClick={() => setFilter('rejected')}
        />
        <Stat label="ربات تأییدنشده" value={unverified} tone="in" Icon={ShieldQuestion} sub="در صف انتظار" />
      </KpiBar>
      <section className="card rise overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--ln)] px-5 py-4">
          <div>
            <h3 className="font-extrabold">درخواست‌های نمایندگی</h3>
            <p className="mt-1 text-xs text-[var(--mu)]">بررسی، تأیید و ساخت فروشگاه نماینده</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Pills
              label="فیلتر وضعیت"
              value={filter}
              onChange={setFilter}
              options={STATUS_PILLS.map(([k, l]) => [k, l, count(k), { warn: k === 'pending' }])}
            />
            <SearchBox value={q} onChange={setQ} placeholder="نام، دامنه، ایمیل، ربات…" label="جستجو در درخواست‌ها" />
          </div>
        </div>
        {failed && (
          <div className="p-4">
            <ErrorBar onRetry={load}>دریافت درخواست‌ها ناموفق بود</ErrorBar>
          </div>
        )}
        <div className="max-h-[70vh] overflow-auto">
          <table className="tbl min-w-[860px]">
            <thead>
              <tr>
                <th>متقاضی</th>
                <th>فروشگاه نمایندگی</th>
                <th>دامنه</th>
                <th>ربات</th>
                <th>فروشگاه مقصد</th>
                <th>ثبت</th>
                <th>وضعیت</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows === null ? (
                Array.from({ length: 4 }, (_, i) => (
                  <tr key={i}>
                    <td colSpan={8}>
                      <div className="skel h-5 w-full" />
                    </td>
                  </tr>
                ))
              ) : shown.length ? (
                shown.map((a) => (
                  <tr key={a.id} className="cursor-pointer" onClick={() => setOpen(a)}>
                    <td>
                      <div className="font-bold">{a.user_name || '—'}</div>
                      <div dir="ltr" className="latin text-right text-xs text-[var(--mu)]">
                        {a.user_email}
                      </div>
                    </td>
                    <td className="font-bold">
                      <span className="inline-flex items-center gap-1.5">
                        <Store size={14} className="text-[var(--mu)]" />
                        {a.store_name}
                      </span>
                    </td>
                    <td>
                      {a.domain ? (
                        <span dir="ltr" className="latin inline-flex items-center gap-1.5 text-xs">
                          <Globe size={13} className="text-[var(--mu)]" />
                          {a.domain}
                        </span>
                      ) : (
                        <span className="text-[var(--mu)]">—</span>
                      )}
                    </td>
                    <td>
                      <BotCell a={a} />
                    </td>
                    <td className="text-xs text-[var(--mu)]">{a.target_store_name || '—'}</td>
                    <td className="text-xs text-[var(--mu)]">{dt(a.created_at)}</td>
                    <td>
                      <Badge s={a.status} />
                    </td>
                    <td>
                      <button
                        className="btn btn-g !py-1.5 !text-xs"
                        onClick={(e) => {
                          e.stopPropagation();
                          setOpen(a);
                        }}
                      >
                        {a.status === 'pending' ? 'بررسی' : 'جزئیات'}
                      </button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={8}>
                    <Empty
                      Icon={UserPlus}
                      title="درخواستی در این فیلتر نیست"
                      text={
                        filter === 'pending' ? 'درخواست جدیدی منتظر بررسی نیست.' : 'فیلتر یا عبارت جستجو را تغییر دهید.'
                      }
                    />
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
      {open && (
        <ReviewDrawer
          key={open.id}
          a={open}
          call={call}
          toast={toast}
          onClose={() => setOpen(null)}
          onDone={() => {
            setOpen(null);
            load();
            api.refresh?.();
          }}
        />
      )}
    </div>
  );
}
