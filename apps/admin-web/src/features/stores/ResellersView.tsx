import { useMemo, useState } from 'react';
import { AlertTriangle, Globe, PlugZap, Store, Unplug } from 'lucide-react';
import { useCall } from '../../api/api.ts';
import { Empty, ErrorBar, KpiBar, Pills, SearchBox, Stat, num, useRows } from '../../shared/kit.tsx';
import { Json, Toast } from '../../shared/types.ts';
import { PROBLEM, FILTERS, BotCell, Loader } from './ResellerParts.tsx';

// Effective bot state computed by Core (stores/bots.py): what the admin should believe about the bot right now.
export default function ResellersView({ api, toast }: { api?: Json; toast: Toast }) {
  const call = useCall(api);
  const { rows, failed, load } = useRows(call, '/api/v1/admin/resellers');
  const [filter, setFilter] = useState('all');
  const [q, setQ] = useState('');
  const [open, setOpen] = useState<Json>(null);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- T-W08: reviewed, dependency list intentionally limited (adding the flagged value risks refetch loops); verify in a browser before changing
  const all = rows || [];
  const inFilter = (x: Json, k: Json) =>
    k === 'all' ||
    (k === 'running' && x.bot.state === 'running') ||
    (k === 'problem' && PROBLEM.has(x.bot.state)) ||
    (k === 'off' && ['disabled', 'no_token', 'stopped'].includes(x.bot.state)) ||
    (k === 'suspended' && x.status === 'suspended');
  const count = (k: Json) => all.filter((x) => inFilter(x, k)).length;
  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    return all.filter(
      (x) =>
        inFilter(x, filter) &&
        (!t ||
          [x.name, x.slug, x.domain, x.owner?.email, x.owner?.name, x.bot.username].some((v) =>
            (v || '').toLowerCase().includes(t),
          )),
    );
  }, [all, filter, q]);

  return (
    <div className="space-y-5">
      <KpiBar cols={4}>
        <Stat
          label="نمایندگان"
          value={all.length}
          tone="in"
          Icon={Store}
          active={filter === 'all'}
          onClick={() => setFilter('all')}
        />
        <Stat
          label="ربات متصل"
          value={count('running')}
          tone="ok"
          Icon={PlugZap}
          active={filter === 'running'}
          onClick={() => setFilter('running')}
        />
        <Stat
          label="ربات دارای مشکل"
          value={count('problem')}
          tone="bd"
          Icon={AlertTriangle}
          active={filter === 'problem'}
          onClick={() => setFilter('problem')}
          sub="خطا یا قطع"
        />
        <Stat
          label="تعلیق"
          value={count('suspended')}
          tone="wn"
          Icon={Unplug}
          active={filter === 'suspended'}
          onClick={() => setFilter('suspended')}
        />
      </KpiBar>
      <section className="card rise overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--ln)] px-5 py-4">
          <div>
            <h3 className="font-extrabold">نمایندگان</h3>
            <p className="mt-1 text-xs text-[var(--mu)]">
              ویرایش فروشگاه، سقف بدهی و ربات تلگرام هر نماینده؛ وضعیت ربات زنده است.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Pills
              label="فیلتر"
              value={filter}
              onChange={setFilter}
              options={FILTERS.map(([k, l]) => [k, l, count(k), { warn: k === 'problem' }])}
            />
            <SearchBox value={q} onChange={setQ} placeholder="نام، دامنه، ایمیل، ربات…" label="جستجو در نمایندگان" />
          </div>
        </div>
        {failed && (
          <div className="p-4">
            <ErrorBar onRetry={load}>دریافت فهرست نمایندگان ناموفق بود</ErrorBar>
          </div>
        )}
        <div className="max-h-[70vh] overflow-auto">
          <table className="tbl min-w-[900px]">
            <thead>
              <tr>
                <th>فروشگاه</th>
                <th>مالک</th>
                <th>دامنه</th>
                <th>ربات</th>
                <th>سقف بدهی</th>
                <th>مشتریان</th>
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
                shown.map((x) => (
                  <tr key={x.id} className="cursor-pointer" onClick={() => setOpen(x.id)}>
                    <td>
                      <div className="font-bold">{x.name}</div>
                      <div dir="ltr" className="latin text-right text-xs text-[var(--mu)]">
                        {x.slug}
                      </div>
                    </td>
                    <td>
                      <div className="font-bold">{x.owner?.name || '—'}</div>
                      <div dir="ltr" className="latin text-right text-xs text-[var(--mu)]">
                        {x.owner?.email}
                      </div>
                    </td>
                    <td>
                      {x.domain ? (
                        <span dir="ltr" className="latin inline-flex items-center gap-1.5 text-xs">
                          <Globe size={13} className="text-[var(--mu)]" />
                          {x.domain}
                        </span>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td>
                      <BotCell bot={x.bot} />
                    </td>
                    <td className="num">{num(x.debt_limit)}</td>
                    <td className="num">{num(x.customers)}</td>
                    <td>
                      <span className={`badge ${x.status === 'active' ? 'b-ok' : 'b-mu'}`}>
                        {x.status === 'active' ? 'فعال' : 'تعلیق'}
                      </span>
                    </td>
                    <td>
                      <button
                        className="btn btn-g !py-1.5 !text-xs"
                        onClick={(e) => {
                          e.stopPropagation();
                          setOpen(x.id);
                        }}
                      >
                        ویرایش
                      </button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={8}>
                    <Empty
                      Icon={Store}
                      title="نماینده‌ای در این فیلتر نیست"
                      text={
                        all.length
                          ? 'فیلتر یا عبارت جستجو را تغییر دهید.'
                          : 'نمایندگان پس از تأیید درخواست نمایندگی اینجا ظاهر می‌شوند.'
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
        <Loader
          key={open}
          id={open}
          call={call}
          toast={toast}
          onClose={() => {
            setOpen(null);
            load();
          }}
          onDone={() => load()}
        />
      )}
    </div>
  );
}

export { BotBadge } from './ResellerParts.tsx';
