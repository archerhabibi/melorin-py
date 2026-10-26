// Stores screen — main store + reseller stores with KPI filters, search, table / card views and a detail drawer.
// Data: GET /api/v1/admin/stores (+ /users to resolve owners). Read-only; reseller management lives in «نمایندگان».
import { useMemo, useState } from 'react';
import { Bot, Building2, Globe, Store, StoreIcon, Users } from 'lucide-react';
import {
  Drawer,
  Empty,
  ErrorBar,
  KpiBar,
  Paginator,
  SearchBox,
  SortSelect,
  Stat,
  ViewToggle,
  tint,
  useRows,
} from './kit.jsx';
import { Badge } from './ui.jsx';
import {
  Avatar,
  Cell2,
  DataGrid,
  Facts,
  PAGE_SIZE,
  ScreenHead,
  Toolbar,
  curLabel,
  downloadCsv,
  indexBy,
  matches,
  pageOf,
  useCall,
} from './dataKit.jsx';

const FILTERS = {
  all: () => true,
  main: (s) => s.kind === 'main',
  reseller: (s) => s.kind === 'reseller',
  suspended: (s) => s.status === 'suspended',
};
const SORTS = {
  name: (a, b) => String(a.name).localeCompare(String(b.name), 'fa'),
  kind: (a, b) => String(a.kind).localeCompare(String(b.kind)) || String(a.name).localeCompare(String(b.name), 'fa'),
  slug: (a, b) => String(a.slug).localeCompare(String(b.slug)),
};

const Kind = ({ s }) =>
  s.kind === 'main' ? (
    <span className="badge b-in">
      <Building2 size={12} />
      فروشگاه اصلی
    </span>
  ) : (
    <span className="badge b-mu">
      <Bot size={12} />
      نماینده
    </span>
  );

export default function StoresView({ api }) {
  const call = useCall(api);
  const stores = useRows(call, '/api/v1/admin/stores');
  const users = useRows(call, '/api/v1/admin/users');
  const [filter, setFilter] = useState('all');
  const [q, setQ] = useState('');
  const [sort, setSort] = useState('kind');
  const [view, setView] = useState('table');
  const [page, setPage] = useState(0);
  const [selId, setSelId] = useState(null);

  const loading = stores.rows === null;
  const all = useMemo(() => stores.rows || [], [stores.rows]);
  const storeMap = useMemo(() => indexBy(all), [all]);
  const userMap = useMemo(() => indexBy(users.rows), [users.rows]);
  const owner = (s) => userMap[s.owner_user_id]?.display_name || userMap[s.owner_user_id]?.email || '';

  const counts = useMemo(
    () => Object.fromEntries(Object.keys(FILTERS).map((k) => [k, all.filter(FILTERS[k]).length])),
    [all],
  );
  const filtered = useMemo(
    () =>
      all
        .filter(FILTERS[filter])
        .filter((s) => matches(q, s.name, s.slug, s.domain, s.bot_username, owner(s)))
        .sort(SORTS[sort]),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [all, filter, q, sort, userMap],
  );
  const size = view === 'cards' ? 12 : PAGE_SIZE;
  const shown = pageOf(filtered, page, size);
  const sel = all.find((s) => s.id === selId) || null;
  const reset = (setter) => (v) => {
    setter(v);
    setPage(0);
  };
  const toggle = (k) => reset(setFilter)(filter === k ? 'all' : k);
  const filtersOn = filter !== 'all' || q.trim() !== '';

  const exportCsv = () =>
    downloadCsv(
      'stores',
      ['نام', 'Slug', 'نوع', 'وضعیت', 'ارز', 'مالک', 'دامنه', 'ربات'],
      filtered.map((s) => [
        s.name,
        s.slug,
        s.kind,
        s.status,
        s.currency,
        owner(s),
        s.domain || '',
        s.bot_username || '',
      ]),
    );

  const columns = [
    {
      key: 'name',
      label: 'فروشگاه',
      render: (s) => (
        <span className="flex items-center gap-2.5">
          <Avatar name={s.name} tone={s.kind === 'main' ? 'ac' : 'in'} />
          <Cell2 main={s.name} sub={s.slug} dir="auto" />
        </span>
      ),
    },
    { key: 'kind', label: 'نوع', render: (s) => <Kind s={s} /> },
    { key: 'owner', label: 'مالک', render: (s) => <span className="text-[13px]">{owner(s) || '—'}</span> },
    {
      key: 'domain',
      label: 'دامنه / ربات',
      render: (s) => (
        <Cell2
          main={s.domain || (s.bot_username ? `@${s.bot_username}` : '')}
          sub={s.domain && s.bot_username ? `@${s.bot_username}` : ''}
          dir="ltr"
        />
      ),
    },
    { key: 'cur', label: 'ارز', render: (s) => <span className="text-[13px]">{curLabel(s.currency)}</span> },
    { key: 'status', label: 'وضعیت', render: (s) => <Badge s={s.status} /> },
  ];

  return (
    <div className="space-y-4">
      <ScreenHead
        title="فروشگاه‌ها"
        count={all.length}
        hint="فروشگاه اصلی و فروشگاه‌های نمایندگان؛ مدیریت نماینده‌ها در بخش «نمایندگان» انجام می‌شود."
        onRefresh={stores.load}
        busy={loading}
        onExport={exportCsv}
        exportDisabled={!filtered.length}
      />
      <KpiBar cols={4}>
        <Stat
          Icon={Store}
          tone="in"
          label="همه فروشگاه‌ها"
          value={counts.all}
          active={filter === 'all'}
          onClick={() => reset(setFilter)('all')}
        />
        <Stat
          Icon={Building2}
          tone="ok"
          label="فروشگاه اصلی"
          value={counts.main}
          active={filter === 'main'}
          onClick={() => toggle('main')}
        />
        <Stat
          Icon={Bot}
          tone="in"
          label="نمایندگان"
          value={counts.reseller}
          active={filter === 'reseller'}
          onClick={() => toggle('reseller')}
        />
        <Stat
          Icon={StoreIcon}
          tone={counts.suspended ? 'bd' : 'mu'}
          label="معلق"
          value={counts.suspended}
          active={filter === 'suspended'}
          onClick={() => toggle('suspended')}
        />
      </KpiBar>
      <Toolbar>
        <SearchBox
          value={q}
          onChange={reset(setQ)}
          label="جستجوی فروشگاه"
          placeholder="نام، slug، دامنه، ربات یا مالک…"
        />
        <SortSelect
          value={sort}
          onChange={reset(setSort)}
          options={[
            ['kind', 'بر اساس نوع'],
            ['name', 'نام (الفبا)'],
            ['slug', 'Slug'],
          ]}
        />
        <ViewToggle
          value={view}
          onChange={reset(setView)}
          options={[
            ['table', 'جدول'],
            ['cards', 'کارت'],
          ]}
        />
        {filtersOn && (
          <button
            className="btn btn-g !py-2 !text-xs"
            onClick={() => {
              setFilter('all');
              setQ('');
              setPage(0);
            }}
          >
            پاک‌کردن فیلترها
          </button>
        )}
      </Toolbar>
      {stores.failed && <ErrorBar onRetry={stores.load}>دریافت فروشگاه‌ها ناموفق بود.</ErrorBar>}
      {view === 'table' || loading ? (
        <DataGrid
          caption="فهرست فروشگاه‌ها"
          columns={columns}
          rows={shown}
          loading={loading}
          onRowClick={(s) => setSelId(s.id)}
          emptyNode={<EmptyStores filtersOn={filtersOn} />}
        />
      ) : shown.length ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {shown.map((s) => (
            <button
              key={s.id}
              type="button"
              className="card card-i rise space-y-3 p-4 text-right"
              onClick={() => setSelId(s.id)}
            >
              <span className="flex items-start justify-between gap-2">
                <span className="flex min-w-0 items-center gap-2.5">
                  <Avatar name={s.name} tone={s.kind === 'main' ? 'ac' : 'in'} size={40} />
                  <Cell2 main={s.name} sub={s.slug} dir="auto" />
                </span>
                <Badge s={s.status} />
              </span>
              <span className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--mu)]">
                <Kind s={s} />
                {s.domain && (
                  <span className="inline-flex items-center gap-1" dir="ltr">
                    <Globe size={12} />
                    {s.domain}
                  </span>
                )}
                {s.bot_username && <span dir="ltr">@{s.bot_username}</span>}
              </span>
              <span className="flex items-center gap-1.5 border-t border-[var(--ln)] pt-2.5 text-xs text-[var(--mu)]">
                <Users size={12} />
                {owner(s) || 'بدون مالک'} · {curLabel(s.currency)}
              </span>
            </button>
          ))}
        </div>
      ) : (
        <div className="card">
          <EmptyStores filtersOn={filtersOn} />
        </div>
      )}
      <Paginator page={page} setPage={setPage} total={filtered.length} pageSize={size} />
      {sel && (
        <StoreDrawer s={sel} owner={owner(sel)} parent={storeMap[sel.parent_store_id]} onClose={() => setSelId(null)} />
      )}
    </div>
  );
}

const EmptyStores = ({ filtersOn }) => (
  <Empty
    Icon={Store}
    title={filtersOn ? 'فروشگاهی با این فیلتر پیدا نشد' : 'هنوز فروشگاهی ثبت نشده'}
    text={
      filtersOn
        ? 'عبارت جستجو یا فیلترها را تغییر دهید.'
        : 'فروشگاه اصلی و نمایندگان پس از ایجاد اینجا نمایش داده می‌شوند.'
    }
  />
);

function StoreDrawer({ s, owner, parent, onClose }) {
  return (
    <Drawer
      title={s.name}
      subtitle={s.slug}
      icon={
        <span className="tile h-10 w-10" style={tint(s.kind === 'main' ? 'ac' : 'in')}>
          <Store size={19} />
        </span>
      }
      onClose={onClose}
    >
      <div className="card flex flex-wrap items-center gap-2 p-4">
        <Badge s={s.status} />
        <Kind s={s} />
      </div>
      <Facts
        items={[
          { label: 'نام', value: s.name },
          { label: 'Slug', value: s.slug, ltr: true, copy: true },
          { label: 'مالک', value: owner },
          { label: 'دامنه', value: s.domain, ltr: true, copy: true },
          { label: 'ربات تلگرام', value: s.bot_username ? `@${s.bot_username}` : '', ltr: true, copy: true },
          { label: 'فروشگاه والد', value: parent?.name },
          { label: 'ارز', value: curLabel(s.currency) },
          { label: 'شناسه فروشگاه', value: s.id, ltr: true, copy: true },
        ]}
      />
    </Drawer>
  );
}
