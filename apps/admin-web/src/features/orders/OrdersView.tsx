import { useMemo, useState } from 'react';
import AttachAccountForm from '../vpn-accounts/AttachAccountForm.tsx';
import { AlertTriangle, CheckCircle2, Hourglass, Package } from 'lucide-react';
import {
  Empty,
  ErrorBar,
  KpiBar,
  Paginator,
  SearchBox,
  SortSelect,
  Stat,
  errText,
  useRows,
} from '../../shared/kit.tsx';
import { typedClient } from '../../api/api.ts';
import { Badge, confirmDialog, promptDialog, sid } from '../../shared/ui.tsx';
import {
  Cell2,
  DataGrid,
  PAGE_SIZE,
  ScreenHead,
  Toolbar,
  When,
  downloadCsv,
  indexBy,
  matches,
  money,
  pageOf,
  useCall,
} from '../../shared/dataKit.tsx';
import { AdminOrderRow, Json, Toast } from '../../shared/types.ts';
import { RETRYABLE, CAP, needsAttention, GROUPS, SORTS } from './OrderParts.tsx';
import { OrderDrawer } from './OrderDrawer.tsx';

export default function OrdersView({ api, toast }: { api?: Json; toast: Toast }) {
  const call = useCall(api);
  const orders = useRows<AdminOrderRow>(call, '/api/v1/admin/orders');
  const stores = useRows(call, '/api/v1/admin/stores');
  const users = useRows(call, '/api/v1/admin/users');
  const [group, setGroup] = useState('all');
  const [q, setQ] = useState('');
  const [store, setStore] = useState('all');
  const [sort, setSort] = useState('new');
  const [page, setPage] = useState(0);
  const [selId, setSelId] = useState<Json>(null);
  const [busy, setBusy] = useState(false);

  const storeMap = useMemo(() => indexBy(stores.rows), [stores.rows]);
  const userMap = useMemo(() => indexBy(users.rows), [users.rows]);
  const loading = orders.rows === null;
  const all = useMemo(() => orders.rows || [], [orders.rows]);

  const storeName = (id: Json) => storeMap[id]?.name || sid(id);
  const who = (id: Json) => userMap[id]?.display_name || userMap[id]?.email || sid(id);
  const mail = (id: Json) => (userMap[id]?.display_name ? userMap[id]?.email : '');

  const counts: Record<string, number | string> = useMemo(() => {
    const c: Record<string, number> = Object.fromEntries(
      Object.keys(GROUPS).map((k) => [k, all.filter(GROUPS[k]).length]),
    );
    const rev: Record<string, number> = {};
    all.filter(GROUPS.done).forEach((o) => {
      rev[o.currency || ''] = (rev[o.currency || ''] || 0) + Number(o.total || 0);
    });
    return {
      ...c,
      revenue: Object.entries(rev)
        .map(([cur, v]) => money(v, cur))
        .join(' · '),
    };
  }, [all]);

  const filtered = useMemo(
    () =>
      all
        .filter(GROUPS[group])
        .filter((o) => store === 'all' || o.store_id === store)
        .filter((o) => matches(q, o.number, who(o.user_id), mail(o.user_id), storeName(o.store_id)))
        .sort(SORTS[sort]),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [all, group, store, q, sort, storeMap, userMap],
  );
  const shown = pageOf(filtered, page);
  const sel = all.find((o) => o.id === selId) || null;

  const reset = (setter: Json) => (v: Json) => {
    setter(v);
    setPage(0);
  };
  const filtersOn = group !== 'all' || store !== 'all' || q.trim() !== '';
  const clear = () => {
    setGroup('all');
    setStore('all');
    setQ('');
    setPage(0);
  };

  const act = async (o: Json, kind: Json, label: Json) => {
    let reason: string | null = '';
    if (kind !== 'retry') {
      reason = await promptDialog(`دلیل ${label} را وارد کنید.`, { title: 'ثبت دلیل' });
      if (reason === null) return;
    }
    if (
      kind === 'refund' &&
      !(await confirmDialog('استرداد این سفارش انجام شود؟ این عملیات مالی است و قابل بازگشت نیست.', {
        title: `استرداد سفارش ${o.number}`,
        danger: true,
        ok: 'استرداد',
      }))
    )
      return;
    setBusy(true);
    try {
      // typed api-client (same transport rules as authFetch); one literal path per action so the schema checks each body
      const client = typedClient(api.base);
      const params = { params: { path: { order_id: o.id } } };
      const { response: r, error } =
        kind === 'retry'
          ? await client.post('/api/v1/admin/orders/{order_id}/retry', params)
          : kind === 'manual-review'
            ? await client.post('/api/v1/admin/orders/{order_id}/manual-review', { ...params, body: { reason } })
            : await client.post('/api/v1/admin/orders/{order_id}/refund', { ...params, body: { reason } });
      if (r.ok) {
        toast(`${label} ثبت شد`);
        await orders.load();
        setSelId(null);
      } else toast(await errText({ json: async () => error }, `${label} ناموفق بود`)); // the client already consumed the body
    } catch {
      toast('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy(false);
    }
  };

  const exportCsv = () =>
    downloadCsv(
      'orders',
      ['شماره', 'مشتری', 'ایمیل', 'فروشگاه', 'مبلغ', 'ارز', 'وضعیت', 'نیازمند بررسی', 'تاریخ'],
      filtered.map((o) => [
        o.number,
        who(o.user_id),
        userMap[o.user_id]?.email || '',
        storeName(o.store_id),
        o.total,
        o.currency,
        o.status,
        o.needs_review ? 'بله' : 'خیر',
        o.created_at,
      ]),
    );

  const columns = [
    {
      key: 'number',
      label: 'شماره',
      render: (o: AdminOrderRow) => (
        <span className="flex items-center gap-1.5">
          <span className="num font-extrabold" dir="ltr">
            {o.number}
          </span>
          {needsAttention(o) && <AlertTriangle size={14} className="text-[var(--wn)]" aria-label="نیازمند بررسی" />}
        </span>
      ),
    },
    {
      key: 'user',
      label: 'مشتری',
      render: (o: AdminOrderRow) => <Cell2 main={who(o.user_id)} sub={mail(o.user_id)} />,
    },
    {
      key: 'store',
      label: 'فروشگاه',
      render: (o: AdminOrderRow) => <span className="text-[13px]">{storeName(o.store_id)}</span>,
    },
    {
      key: 'total',
      label: 'مبلغ',
      render: (o: AdminOrderRow) => <span className="num font-bold">{money(o.total, o.currency)}</span>,
    },
    { key: 'status', label: 'وضعیت', m: 'head', render: (o: AdminOrderRow) => <Badge s={o.status} /> },
    { key: 'at', label: 'ثبت', render: (o: AdminOrderRow) => <When v={o.created_at} /> },
  ];

  return (
    <div className="space-y-4">
      <ScreenHead
        title="سفارش‌ها"
        count={all.length}
        hint="همه سفارش‌های فروشگاه‌ها؛ برای مشاهده جزئیات و اقدام، روی هر سفارش بزنید."
        onRefresh={orders.load}
        busy={loading}
        onExport={exportCsv}
        exportDisabled={!filtered.length}
      />
      <KpiBar cols={4}>
        <Stat
          Icon={Package}
          tone="in"
          label="همه سفارش‌ها"
          value={counts.all}
          active={group === 'all'}
          onClick={() => reset(setGroup)('all')}
        />
        <Stat
          Icon={CheckCircle2}
          tone="ok"
          label="تکمیل‌شده"
          value={counts.done}
          sub={counts.revenue || undefined}
          active={group === 'done'}
          onClick={() => reset(setGroup)(group === 'done' ? 'all' : 'done')}
        />
        <Stat
          Icon={Hourglass}
          tone="in"
          label="در جریان"
          value={counts.progress}
          active={group === 'progress'}
          onClick={() => reset(setGroup)(group === 'progress' ? 'all' : 'progress')}
        />
        <Stat
          Icon={AlertTriangle}
          tone={counts.attention ? 'wn' : 'mu'}
          label="نیازمند توجه"
          value={counts.attention}
          sub={counts.closed ? `${counts.closed.toLocaleString('fa-IR')} لغو/مسترد` : undefined}
          active={group === 'attention'}
          onClick={() => reset(setGroup)(group === 'attention' ? 'all' : 'attention')}
        />
      </KpiBar>
      <Toolbar>
        <SearchBox
          value={q}
          onChange={reset(setQ)}
          hotkey
          label="جستجوی سفارش"
          placeholder="شماره سفارش، نام یا ایمیل مشتری، فروشگاه…"
        />
        <select
          aria-label="فیلتر فروشگاه"
          className="inp !w-auto !py-2 !text-xs font-bold"
          value={store}
          onChange={(e) => reset(setStore)(e.target.value)}
        >
          <option value="all">همه فروشگاه‌ها</option>
          {(stores.rows || []).map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
        <SortSelect
          value={sort}
          onChange={reset(setSort)}
          options={[
            ['new', 'جدیدترین'],
            ['old', 'قدیمی‌ترین'],
            ['high', 'بیشترین مبلغ'],
          ]}
        />
        {filtersOn && (
          <button className="btn btn-g !py-2 !text-xs" onClick={clear}>
            پاک‌کردن فیلترها
          </button>
        )}
      </Toolbar>
      {orders.failed && <ErrorBar onRetry={orders.load}>دریافت سفارش‌ها ناموفق بود.</ErrorBar>}
      <DataGrid
        caption="فهرست سفارش‌ها"
        columns={columns}
        rows={shown}
        loading={loading}
        onRowClick={(o: AdminOrderRow) => setSelId(o.id)}
        emptyNode={
          <Empty
            Icon={Package}
            title={filtersOn ? 'سفارشی با این فیلتر پیدا نشد' : 'هنوز سفارشی ثبت نشده'}
            text={
              filtersOn
                ? 'جستجو یا فیلترها را تغییر دهید.'
                : 'با اولین خرید مشتری، سفارش در این فهرست نمایش داده می‌شود.'
            }
          >
            {filtersOn && (
              <button className="btn btn-g" onClick={clear}>
                نمایش همه سفارش‌ها
              </button>
            )}
          </Empty>
        }
      />
      <Paginator page={page} setPage={setPage} total={filtered.length} pageSize={PAGE_SIZE} />
      {all.length >= CAP && (
        <p className="text-center text-[11px] text-[var(--mu)]">
          فقط {CAP.toLocaleString('fa-IR')} سفارش اخیر نمایش داده می‌شود؛ برای تاریخچه کامل از «خروجی CSV سفارش‌ها» در
          پالت فرمان (Ctrl+K) استفاده کنید.
        </p>
      )}
      {sel && (
        <OrderDrawer
          o={sel}
          busy={busy}
          customer={who(sel.user_id)}
          email={userMap[sel.user_id]?.email}
          store={storeName(sel.store_id)}
          onClose={() => setSelId(null)}
          act={act}
          attach={
            RETRYABLE.includes(sel.status) ? (
              <AttachAccountForm
                call={call}
                orderId={sel.id}
                toast={toast}
                onDone={async () => {
                  await orders.load();
                  setSelId(null);
                }}
              />
            ) : null
          }
        />
      )}
    </div>
  );
}

export { OrderFlow } from './OrderParts.tsx';
