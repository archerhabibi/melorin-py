// Orders screen — KPI filters, search, store filter, sortable list and a detail drawer with the
// admin actions the order state machine allows (retry / manual review / refund).
// Data: GET /api/v1/admin/orders (+ /stores and /users to resolve names); actions: POST …/{retry|manual-review|refund}.
import { useMemo, useState } from 'react';
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ClipboardCheck,
  Clock,
  Hourglass,
  Minus,
  Package,
  RotateCcw,
  Undo2,
  X,
  XCircle,
} from 'lucide-react';
import {
  Drawer,
  Empty,
  ErrorBar,
  KpiBar,
  Paginator,
  SearchBox,
  SortSelect,
  Stat,
  errText,
  tint,
  useRows,
} from './kit.jsx';
import { Badge, confirmDialog, dt, promptDialog, sid } from './ui.jsx';
import {
  Cell2,
  DataGrid,
  Facts,
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
} from './dataKit.jsx';

const IN_PROGRESS = ['pending', 'payment_pending', 'paid', 'processing', 'provisioning'];
const ATTENTION = ['provisioning_failed', 'manual_review', 'refund_pending', 'payment_failed'];
const CLOSED = ['cancelled', 'refunded'];
// Mirror apps/api/melorin/domain/order_state.py so the UI never offers an action the API would refuse.
const RETRYABLE = ['provisioning_failed', 'manual_review'];
const REVIEWABLE = ['provisioning_failed', 'refund_pending'];
const REFUNDABLE = ['paid', 'provisioning_failed', 'manual_review', 'completed'];
const CAP = 200; // the endpoint returns the latest 200 orders

// Where an order is on its way: register → pay → build the account → done. `done` = steps fully completed;
// the next step is the active one (tone = how it is going). `as` swaps in a label when the step went off the happy path.
const STEPS = ['ثبت سفارش', 'پرداخت', 'ساخت اکانت', 'تکمیل'];
const PROGRESS = {
  pending: { done: 1, tone: 'wn' },
  payment_pending: { done: 1, tone: 'wn' },
  payment_failed: { done: 1, tone: 'bd', as: 'پرداخت ناموفق' },
  paid: { done: 2, tone: 'in' },
  processing: { done: 2, tone: 'in' },
  provisioning: { done: 2, tone: 'in' },
  manual_review: { done: 2, tone: 'wn', as: 'بررسی دستی' },
  provisioning_failed: { done: 2, tone: 'bd', as: 'ساخت ناموفق' },
  completed: { done: 4, tone: 'ok' },
  refund_pending: { done: 3, tone: 'wn', as: 'در انتظار استرداد' },
  refunded: { done: 3, tone: 'mu', as: 'مسترد شد' },
  cancelled: { done: 1, tone: 'mu', as: 'لغو شد' },
};
const NodeIcon = ({ tone, status }) =>
  tone === 'bd' ? (
    <X size={14} />
  ) : tone === 'wn' ? (
    <Clock size={14} />
  ) : tone === 'mu' ? (
    status === 'refunded' ? (
      <Undo2 size={13} />
    ) : (
      <Minus size={14} />
    )
  ) : (
    <i className="block h-2 w-2 rounded-full bg-current" />
  );

/** Order lifecycle tracker shown in the drawer. Renders nothing for a status it does not know. */
export function OrderFlow({ status }) {
  const p = PROGRESS[status];
  if (!p) return null;
  const cur = p.done < STEPS.length ? p.done : -1;
  const label = (i) => (i === cur && p.as ? p.as : STEPS[i]);
  return (
    <ol className="ostep" aria-label="مراحل سفارش" style={{ '--t': `var(--${p.tone})` }}>
      {STEPS.map((_, i) => {
        const state = i < p.done ? 'done' : i === cur ? 'cur' : 'todo';
        return (
          <li key={i} className={state} aria-current={state === 'cur' ? 'step' : undefined}>
            <span className="dot" aria-hidden="true">
              {state === 'done' ? (
                <Check size={14} strokeWidth={3} />
              ) : state === 'cur' ? (
                <NodeIcon tone={p.tone} status={status} />
              ) : null}
            </span>
            <span>{label(i)}</span>
          </li>
        );
      })}
    </ol>
  );
}

const needsAttention = (o) => !!o.needs_review || ATTENTION.includes(o.status);
const GROUPS = {
  all: () => true,
  done: (o) => o.status === 'completed',
  progress: (o) => IN_PROGRESS.includes(o.status),
  attention: needsAttention,
  closed: (o) => CLOSED.includes(o.status),
};
const SORTS = {
  new: (a, b) => String(b.created_at).localeCompare(String(a.created_at)),
  old: (a, b) => String(a.created_at).localeCompare(String(b.created_at)),
  high: (a, b) => Number(b.total || 0) - Number(a.total || 0),
};

export default function OrdersView({ api, toast }) {
  const call = useCall(api);
  const orders = useRows(call, '/api/v1/admin/orders');
  const stores = useRows(call, '/api/v1/admin/stores');
  const users = useRows(call, '/api/v1/admin/users');
  const [group, setGroup] = useState('all');
  const [q, setQ] = useState('');
  const [store, setStore] = useState('all');
  const [sort, setSort] = useState('new');
  const [page, setPage] = useState(0);
  const [selId, setSelId] = useState(null);
  const [busy, setBusy] = useState(false);

  const storeMap = useMemo(() => indexBy(stores.rows), [stores.rows]);
  const userMap = useMemo(() => indexBy(users.rows), [users.rows]);
  const loading = orders.rows === null;
  const all = useMemo(() => orders.rows || [], [orders.rows]);

  const storeName = (id) => storeMap[id]?.name || sid(id);
  const who = (id) => userMap[id]?.display_name || userMap[id]?.email || sid(id);
  const mail = (id) => (userMap[id]?.display_name ? userMap[id]?.email : '');

  const counts = useMemo(() => {
    const c = Object.fromEntries(Object.keys(GROUPS).map((k) => [k, all.filter(GROUPS[k]).length]));
    const rev = {};
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

  const reset = (setter) => (v) => {
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

  const act = async (o, kind, label) => {
    let reason = '';
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
      const r = await call(`/api/v1/admin/orders/${o.id}/${kind}`, {
        method: 'POST',
        body: JSON.stringify({ reason }),
      });
      if (r.ok) {
        toast(`${label} ثبت شد`);
        await orders.load();
        setSelId(null);
      } else toast(await errText(r, `${label} ناموفق بود`));
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
      render: (o) => (
        <span className="flex items-center gap-1.5">
          <span className="num font-extrabold" dir="ltr">
            {o.number}
          </span>
          {needsAttention(o) && <AlertTriangle size={14} className="text-[var(--wn)]" aria-label="نیازمند بررسی" />}
        </span>
      ),
    },
    { key: 'user', label: 'مشتری', render: (o) => <Cell2 main={who(o.user_id)} sub={mail(o.user_id)} /> },
    { key: 'store', label: 'فروشگاه', render: (o) => <span className="text-[13px]">{storeName(o.store_id)}</span> },
    { key: 'total', label: 'مبلغ', render: (o) => <span className="num font-bold">{money(o.total, o.currency)}</span> },
    { key: 'status', label: 'وضعیت', m: 'head', render: (o) => <Badge s={o.status} /> },
    { key: 'at', label: 'ثبت', render: (o) => <When v={o.created_at} /> },
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
        onRowClick={(o) => setSelId(o.id)}
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
        />
      )}
    </div>
  );
}

function OrderDrawer({ o, busy, customer, email, store, onClose, act }) {
  const canRetry = RETRYABLE.includes(o.status);
  const canReview = REVIEWABLE.includes(o.status);
  const canRefund = REFUNDABLE.includes(o.status);
  const none = !canRetry && !canReview && !canRefund;
  return (
    <Drawer
      title={`سفارش ${o.number}`}
      subtitle={`${store} · ${dt(o.created_at)}`}
      icon={
        <span className="tile h-10 w-10" style={tint(needsAttention(o) ? 'wn' : 'in')}>
          <Package size={19} />
        </span>
      }
      busy={busy}
      onClose={onClose}
      footer={
        <>
          {canRetry && (
            <button className="btn !py-2 !text-sm" disabled={busy} onClick={() => act(o, 'retry', 'تلاش مجدد')}>
              <RotateCcw size={14} />
              تلاش مجدد
            </button>
          )}
          {canReview && (
            <button
              className="btn btn-g !py-2 !text-sm"
              disabled={busy}
              onClick={() => act(o, 'manual-review', 'بررسی دستی')}
            >
              <ClipboardCheck size={14} />
              ارجاع به بررسی دستی
            </button>
          )}
        </>
      }
      danger={
        canRefund && (
          <button
            className="btn btn-g btn-d !py-2 !text-sm"
            disabled={busy}
            onClick={() => act(o, 'refund', 'استرداد')}
          >
            <Undo2 size={14} />
            استرداد
          </button>
        )
      }
    >
      <div className="card flex flex-wrap items-center justify-between gap-3 p-4">
        <div>
          <p className="text-xs text-[var(--mu)]">مبلغ سفارش</p>
          <p className="num mt-1 text-2xl font-extrabold">{money(o.total, o.currency)}</p>
        </div>
        <Badge s={o.status} />
      </div>
      {PROGRESS[o.status] && (
        <section className="card p-4">
          <h3 className="mb-3 text-[13px] font-extrabold">مسیر سفارش</h3>
          <OrderFlow status={o.status} />
        </section>
      )}
      {needsAttention(o) && (
        <p className="flex items-start gap-2 rounded-xl bg-[var(--wnb)] p-3 text-xs leading-6 text-[var(--wn)]">
          <AlertTriangle size={15} className="mt-0.5 shrink-0" />
          این سفارش نیاز به بررسی دارد. از دکمه‌های پایین برای تلاش مجدد، ارجاع به بررسی دستی یا استرداد استفاده کنید.
        </p>
      )}
      {none && (
        <p className="flex items-start gap-2 rounded-xl bg-[var(--mb)] p-3 text-xs leading-6 text-[var(--mu)]">
          <XCircle size={15} className="mt-0.5 shrink-0" />
          در وضعیت فعلی، اقدام دستی برای این سفارش مجاز نیست.
        </p>
      )}
      <Facts
        items={[
          { label: 'شماره سفارش', value: o.number, ltr: true, copy: true },
          { label: 'مشتری', value: customer },
          { label: 'ایمیل', value: email, ltr: true, copy: true },
          { label: 'فروشگاه', value: store },
          { label: 'تاریخ ثبت', value: dt(o.created_at) },
          { label: 'شناسه سفارش', value: o.id, ltr: true, copy: true },
        ]}
      />
    </Drawer>
  );
}
