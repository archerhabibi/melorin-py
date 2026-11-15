import { useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Clock, Inbox, RefreshCw, Store, UserCog } from 'lucide-react';
import { useCall as useApiCall } from '../../api/api.ts';
import { Badge, dt } from '../../ui.tsx';
import { Empty, ErrorBar, KpiBar, Pills, SearchBox, Segmented, Stat, errText, num, useRows } from '../../kit.tsx';
import type { Json, Toast } from '../../types.ts';
import { LABEL, ltr, STATUS_PILLS, REQUEST_PILLS, KindBadge } from './panelAdminsShared.tsx';
import { RequestDrawer } from './PanelRequestDrawer.tsx';
import { AdminDrawer } from './PanelAdminDrawer.tsx';

export default function PanelAdminsView({ api, toast }: { api?: Json; toast: Toast }) {
  const call = useApiCall(api);
  const admins = useRows(call, '/api/v1/admin/panel-admins');
  const requests = useRows(call, '/api/v1/admin/panel-admin-requests?status='); // empty status = every request
  const [tab, setTab] = useState('admins');
  const [filter, setFilter] = useState('all');
  const [reqFilter, setReqFilter] = useState('pending');
  const [q, setQ] = useState('');
  const [open, setOpen] = useState<Json>(null);
  const [openReq, setOpenReq] = useState<Json>(null);
  const [syncing, setSyncing] = useState(false);

  const rows = useMemo(() => admins.rows || [], [admins.rows]);
  const reqs = useMemo(() => requests.rows || [], [requests.rows]);
  const match = (r: Json, f: Json) => f === 'all' || (f === 'unsynced' ? !r.profile_synced : r.status === f);
  const count = (f: Json) => rows.filter((r) => match(r, f)).length;
  const reqCount = (f: Json) => (f === 'all' ? reqs.length : reqs.filter((r) => r.status === f).length);
  const pendingReqs = reqCount('pending');
  const needsCare = rows.filter((r) => r.status === 'error' || !r.profile_synced).length;

  const shownRows = useMemo(() => {
    const t = q.trim().toLowerCase();
    return rows.filter(
      (r) =>
        match(r, filter) &&
        (!t || [r.store_name, r.username, r.panel_name].some((v) => (v || '').toLowerCase().includes(t))),
    );
  }, [rows, filter, q]);
  const shownReqs = useMemo(() => reqs.filter((r) => reqFilter === 'all' || r.status === reqFilter), [reqs, reqFilter]);

  const reload = () => {
    admins.load();
    requests.load();
    api.refresh?.();
  };
  const sync = async () => {
    setSyncing(true);
    try {
      const r = await call('/api/v1/admin/panel-admins/sync', { method: 'POST', body: '{}' });
      if (!r.ok) return toast(await errText(r, 'همگام‌سازی ناموفق بود'));
      const d = await r.json();
      toast(`${num(d.planned)} ادمین برنامه‌ریزی شد · ${num(d.synced)} همگام · ${num(d.failed)} ناموفق`);
      reload();
    } catch {
      toast('ارتباط با سرور برقرار نشد');
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="space-y-5">
      <KpiBar cols={4}>
        <Stat
          label="ادمین فعال"
          value={admins.rows === null ? null : count('active')}
          tone="ok"
          Icon={CheckCircle2}
          active={tab === 'admins' && filter === 'active'}
          onClick={() => {
            setTab('admins');
            setFilter('active');
          }}
        />
        <Stat
          label="نیازمند توجه"
          value={admins.rows === null ? null : needsCare}
          tone="bd"
          Icon={AlertTriangle}
          sub="خطا یا پروفایل همگام‌نشده"
          active={tab === 'admins' && filter === 'error'}
          onClick={() => {
            setTab('admins');
            setFilter('error');
          }}
        />
        <Stat
          label="در حال راه‌اندازی"
          value={admins.rows === null ? null : count('pending')}
          tone="in"
          Icon={Clock}
          active={tab === 'admins' && filter === 'pending'}
          onClick={() => {
            setTab('admins');
            setFilter('pending');
          }}
        />
        <Stat
          label="درخواست در انتظار"
          value={requests.rows === null ? null : pendingReqs}
          tone="wn"
          Icon={Inbox}
          active={tab === 'requests'}
          onClick={() => {
            setTab('requests');
            setReqFilter('pending');
          }}
        />
      </KpiBar>

      <section className="card rise overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--ln)] px-5 py-4">
          <div>
            <h3 className="font-extrabold">اپراتور پنل فروشگاه</h3>
            <p className="mt-1 text-xs text-[var(--mu)]">
              برای هر فروشگاه یک ادمین Operator روی هر پنل PasarGuard؛ همهٔ اکانت‌های آن فروشگاه زیر همین ادمین ساخته
              می‌شوند.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Segmented
              label="بخش"
              value={tab}
              onChange={setTab}
              options={[
                ['admins', 'ادمین‌ها'],
                ['requests', pendingReqs ? `درخواست‌ها (${num(pendingReqs)})` : 'درخواست‌ها'],
              ]}
            />
            <button className="btn btn-g !py-2 !text-sm" disabled={syncing} onClick={sync}>
              <RefreshCw size={15} className={syncing ? 'animate-spin' : ''} />
              همگام‌سازی اکنون
            </button>
          </div>
        </div>

        {tab === 'admins' ? (
          <>
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--ln)] px-5 py-3">
              <Pills
                label="فیلتر وضعیت"
                value={filter}
                onChange={setFilter}
                options={STATUS_PILLS.map(([k, l]) => [k, l, count(k), { warn: k === 'error' || k === 'unsynced' }])}
              />
              <SearchBox value={q} onChange={setQ} placeholder="فروشگاه، ادمین، پنل…" label="جستجو در ادمین‌ها" />
            </div>
            {admins.failed && (
              <div className="p-4">
                <ErrorBar onRetry={admins.load}>دریافت ادمین‌ها ناموفق بود</ErrorBar>
              </div>
            )}
            <div className="max-h-[65vh] overflow-auto">
              <table className="tbl min-w-[820px]">
                <thead>
                  <tr>
                    <th>فروشگاه</th>
                    <th>پنل</th>
                    <th>ادمین</th>
                    <th>وضعیت</th>
                    <th>پروفایل</th>
                    <th>آخرین همگام‌سازی</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {admins.rows === null ? (
                    Array.from({ length: 4 }, (_, i) => (
                      <tr key={i}>
                        <td colSpan={7}>
                          <div className="skel h-5 w-full" />
                        </td>
                      </tr>
                    ))
                  ) : shownRows.length ? (
                    shownRows.map((r) => (
                      <tr key={r.id}>
                        <td>
                          <span className="inline-flex items-center gap-2 font-bold">
                            <Store size={14} className="text-[var(--mu)]" />
                            {r.store_name}
                            <KindBadge kind={r.store_kind} />
                          </span>
                        </td>
                        <td className="text-xs">{r.panel_name}</td>
                        <td>{ltr(r.username)}</td>
                        <td>
                          <Badge s={r.status} />
                        </td>
                        <td>
                          {r.profile_synced ? (
                            <CheckCircle2 size={15} className="text-[var(--ok)]" aria-label="همگام" />
                          ) : (
                            <span className="badge b-wn">منتظر پنل</span>
                          )}
                        </td>
                        <td className="text-xs text-[var(--mu)]">{dt(r.synced_at)}</td>
                        <td>
                          <button className="btn btn-g !py-1.5 !text-xs" onClick={() => setOpen(r)}>
                            مدیریت
                          </button>
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={7}>
                        <Empty
                          Icon={UserCog}
                          title={rows.length ? 'موردی در این فیلتر نیست' : 'هنوز ادمینی ساخته نشده'}
                          text={
                            rows.length
                              ? 'فیلتر یا عبارت جستجو را تغییر دهید.'
                              : 'یک پنل PasarGuard فعال اضافه کنید یا «همگام‌سازی اکنون» را بزنید؛ ادمین هر فروشگاه خودکار ساخته می‌شود.'
                          }
                        />
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <>
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--ln)] px-5 py-3">
              <Pills
                label="فیلتر درخواست‌ها"
                value={reqFilter}
                onChange={setReqFilter}
                options={REQUEST_PILLS.map(([k, l]) => [k, l, reqCount(k), { warn: k === 'pending' }])}
              />
            </div>
            {requests.failed && (
              <div className="p-4">
                <ErrorBar onRetry={requests.load}>دریافت درخواست‌ها ناموفق بود</ErrorBar>
              </div>
            )}
            <div className="max-h-[65vh] overflow-auto">
              <table className="tbl min-w-[760px]">
                <thead>
                  <tr>
                    <th>فروشگاه</th>
                    <th>موارد درخواستی</th>
                    <th>پیام</th>
                    <th>ثبت</th>
                    <th>وضعیت</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {requests.rows === null ? (
                    Array.from({ length: 3 }, (_, i) => (
                      <tr key={i}>
                        <td colSpan={6}>
                          <div className="skel h-5 w-full" />
                        </td>
                      </tr>
                    ))
                  ) : shownReqs.length ? (
                    shownReqs.map((r) => (
                      <tr key={r.id}>
                        <td className="font-bold">{r.store_name || '—'}</td>
                        <td>
                          <span className="flex flex-wrap gap-1">
                            {Object.keys(r.changes || {}).map((k) => (
                              <span key={k} className="badge b-mu">
                                {LABEL[k] || k}
                              </span>
                            ))}
                          </span>
                        </td>
                        <td className="max-w-[220px] truncate text-xs text-[var(--mu)]">{r.message || '—'}</td>
                        <td className="text-xs text-[var(--mu)]">{dt(r.created_at)}</td>
                        <td>
                          <Badge s={r.status} />
                        </td>
                        <td>
                          <button className="btn btn-g !py-1.5 !text-xs" onClick={() => setOpenReq(r)}>
                            {r.status === 'pending' ? 'بررسی' : 'جزئیات'}
                          </button>
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={6}>
                        <Empty
                          Icon={Inbox}
                          title="درخواستی در این فیلتر نیست"
                          text={reqFilter === 'pending' ? 'درخواست جدیدی منتظر بررسی نیست.' : 'فیلتر را تغییر دهید.'}
                        />
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      {open && (
        <AdminDrawer
          key={open.id}
          row={open}
          call={call}
          toast={toast}
          onClose={() => setOpen(null)}
          onDone={() => {
            setOpen(null);
            reload();
          }}
        />
      )}
      {openReq && (
        <RequestDrawer
          key={openReq.id}
          req={openReq}
          call={call}
          toast={toast}
          onClose={() => setOpenReq(null)}
          onDone={() => {
            setOpenReq(null);
            reload();
          }}
        />
      )}
    </div>
  );
}
