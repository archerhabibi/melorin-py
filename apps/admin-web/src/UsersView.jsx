// Users screen — KPI filters, search, sorting and a detail drawer (incl. the stores a user owns).
// Data: GET /api/v1/admin/users (latest 500) and /stores for ownership. Read-only.
import { useMemo, useState } from 'react';
import { ShieldCheck, Store, UserCheck, UserX, Users } from 'lucide-react';
import { Drawer, Empty, ErrorBar, KpiBar, Paginator, SearchBox, SortSelect, Stat, tint, useRows } from './kit.jsx';
import { Badge, dt } from './ui.jsx';
import {
  Avatar,
  Cell2,
  DataGrid,
  Facts,
  PAGE_SIZE,
  ScreenHead,
  Toolbar,
  When,
  downloadCsv,
  matches,
  pageOf,
  useCall,
} from './dataKit.jsx';

const CAP = 500;
const FILTERS = {
  all: () => true,
  active: (u) => u.is_active,
  inactive: (u) => !u.is_active,
  admin: (u) => u.is_super_admin,
};
const SORTS = {
  new: (a, b) => String(b.created_at).localeCompare(String(a.created_at)),
  old: (a, b) => String(a.created_at).localeCompare(String(b.created_at)),
  name: (a, b) => String(a.display_name || a.email || '').localeCompare(String(b.display_name || b.email || ''), 'fa'),
};
const title = (u) => u.display_name || u.email || 'بدون نام';

const Role = ({ u }) =>
  u.is_super_admin ? (
    <span className="badge b-in">
      <ShieldCheck size={12} />
      ادمین کل
    </span>
  ) : (
    <span className="badge b-mu">کاربر</span>
  );

export default function UsersView({ api }) {
  const call = useCall(api);
  const users = useRows(call, '/api/v1/admin/users');
  const stores = useRows(call, '/api/v1/admin/stores');
  const [filter, setFilter] = useState('all');
  const [q, setQ] = useState('');
  const [sort, setSort] = useState('new');
  const [page, setPage] = useState(0);
  const [selId, setSelId] = useState(null);

  const loading = users.rows === null;
  const all = useMemo(() => users.rows || [], [users.rows]);
  const owned = useMemo(() => {
    const m = {};
    (stores.rows || []).forEach((s) => {
      if (s.owner_user_id) (m[s.owner_user_id] ||= []).push(s);
    });
    return m;
  }, [stores.rows]);

  const counts = useMemo(
    () => Object.fromEntries(Object.keys(FILTERS).map((k) => [k, all.filter(FILTERS[k]).length])),
    [all],
  );
  const filtered = useMemo(
    () =>
      all
        .filter(FILTERS[filter])
        .filter((u) => matches(q, u.email, u.display_name))
        .sort(SORTS[sort]),
    [all, filter, q, sort],
  );
  const shown = pageOf(filtered, page);
  const sel = all.find((u) => u.id === selId) || null;
  const reset = (setter) => (v) => {
    setter(v);
    setPage(0);
  };
  const toggle = (k) => reset(setFilter)(filter === k ? 'all' : k);
  const filtersOn = filter !== 'all' || q.trim() !== '';

  const exportCsv = () =>
    downloadCsv(
      'users',
      ['نام', 'ایمیل', 'فعال', 'ادمین کل', 'تعداد فروشگاه', 'تاریخ عضویت'],
      filtered.map((u) => [
        u.display_name || '',
        u.email || '',
        u.is_active ? 'بله' : 'خیر',
        u.is_super_admin ? 'بله' : 'خیر',
        (owned[u.id] || []).length,
        u.created_at,
      ]),
    );

  const columns = [
    {
      key: 'user',
      label: 'کاربر',
      render: (u) => (
        <span className="flex items-center gap-2.5">
          <Avatar name={title(u)} tone={u.is_super_admin ? 'ac' : 'in'} />
          <Cell2 main={title(u)} sub={u.display_name ? u.email : ''} dir="auto" />
        </span>
      ),
    },
    { key: 'role', label: 'نقش', render: (u) => <Role u={u} /> },
    { key: 'status', label: 'وضعیت', m: 'head', render: (u) => <Badge s={u.is_active ? 'active' : 'disabled'} /> },
    {
      key: 'stores',
      label: 'فروشگاه‌ها',
      render: (u) => {
        const n = (owned[u.id] || []).length;
        return n ? (
          <span className="num inline-flex items-center gap-1 text-[13px] font-bold">
            <Store size={13} className="text-[var(--mu)]" />
            {n.toLocaleString('fa-IR')}
          </span>
        ) : (
          <span className="text-[var(--mu)]">—</span>
        );
      },
    },
    { key: 'at', label: 'عضویت', render: (u) => <When v={u.created_at} /> },
  ];

  return (
    <div className="space-y-4">
      <ScreenHead
        title="کاربران"
        count={all.length}
        hint="حساب‌های ثبت‌شده در پلتفرم؛ برای دیدن جزئیات و فروشگاه‌های هر کاربر روی ردیف بزنید."
        onRefresh={users.load}
        busy={loading}
        onExport={exportCsv}
        exportDisabled={!filtered.length}
      />
      <KpiBar cols={4}>
        <Stat
          Icon={Users}
          tone="in"
          label="همه کاربران"
          value={counts.all}
          active={filter === 'all'}
          onClick={() => reset(setFilter)('all')}
        />
        <Stat
          Icon={UserCheck}
          tone="ok"
          label="فعال"
          value={counts.active}
          active={filter === 'active'}
          onClick={() => toggle('active')}
        />
        <Stat
          Icon={UserX}
          tone={counts.inactive ? 'bd' : 'mu'}
          label="غیرفعال"
          value={counts.inactive}
          active={filter === 'inactive'}
          onClick={() => toggle('inactive')}
        />
        <Stat
          Icon={ShieldCheck}
          tone="in"
          label="ادمین کل"
          value={counts.admin}
          active={filter === 'admin'}
          onClick={() => toggle('admin')}
        />
      </KpiBar>
      <Toolbar>
        <SearchBox value={q} onChange={reset(setQ)} hotkey label="جستجوی کاربر" placeholder="نام یا ایمیل…" />
        <SortSelect
          value={sort}
          onChange={reset(setSort)}
          options={[
            ['new', 'جدیدترین'],
            ['old', 'قدیمی‌ترین'],
            ['name', 'نام (الفبا)'],
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
      {users.failed && <ErrorBar onRetry={users.load}>دریافت کاربران ناموفق بود.</ErrorBar>}
      <DataGrid
        caption="فهرست کاربران"
        columns={columns}
        rows={shown}
        loading={loading}
        onRowClick={(u) => setSelId(u.id)}
        emptyNode={
          <Empty
            Icon={Users}
            title={filtersOn ? 'کاربری با این فیلتر پیدا نشد' : 'هنوز کاربری ثبت‌نام نکرده'}
            text={
              filtersOn
                ? 'عبارت جستجو یا فیلترها را تغییر دهید.'
                : 'کاربران پس از اولین ورود یا ثبت‌نام اینجا نمایش داده می‌شوند.'
            }
          />
        }
      />
      <Paginator page={page} setPage={setPage} total={filtered.length} pageSize={PAGE_SIZE} />
      {all.length >= CAP && (
        <p className="text-center text-[11px] text-[var(--mu)]">
          فقط {CAP.toLocaleString('fa-IR')} کاربر اخیر نمایش داده می‌شود.
        </p>
      )}
      {sel && <UserDrawer u={sel} stores={owned[sel.id] || []} onClose={() => setSelId(null)} />}
    </div>
  );
}

function UserDrawer({ u, stores, onClose }) {
  return (
    <Drawer
      title={title(u)}
      subtitle={u.display_name ? u.email : undefined}
      icon={<Avatar name={title(u)} tone={u.is_super_admin ? 'ac' : 'in'} size={40} />}
      onClose={onClose}
    >
      <div className="card flex flex-wrap items-center gap-2 p-4">
        <Badge s={u.is_active ? 'active' : 'disabled'} />
        <Role u={u} />
      </div>
      <Facts
        items={[
          { label: 'نام نمایشی', value: u.display_name },
          { label: 'ایمیل', value: u.email, ltr: true, copy: true },
          { label: 'تاریخ عضویت', value: dt(u.created_at) },
          { label: 'شناسه کاربر', value: u.id, ltr: true, copy: true },
        ]}
      />
      <section className="card p-4">
        <h3 className="mb-3 flex items-center gap-2 text-[13px] font-extrabold">
          <span className="tile h-8 w-8" style={tint('in')}>
            <Store size={15} />
          </span>
          فروشگاه‌های این کاربر
        </h3>
        {stores.length ? (
          <ul className="space-y-2">
            {stores.map((s) => (
              <li
                key={s.id}
                className="flex items-center justify-between gap-3 rounded-xl bg-[var(--sf2)] px-3 py-2 text-sm"
              >
                <span className="min-w-0">
                  <b className="block truncate">{s.name}</b>
                  <span className="block truncate text-[11px] text-[var(--mu)]" dir="ltr">
                    {s.slug}
                  </span>
                </span>
                <Badge s={s.status} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-[var(--mu)]">این کاربر مالک هیچ فروشگاهی نیست.</p>
        )}
      </section>
    </Drawer>
  );
}
