// VPN accounts screen — server-side search / filter / paging over every store's accounts.
// Data: GET /api/v1/admin/vpn-accounts (q, state, store_id, limit, offset; total in X-Total-Count).
import { useEffect, useMemo, useState } from 'react';
import { Clock, Gauge, ShieldCheck, ShieldOff, Server, Timer } from 'lucide-react';
import {
  Bar,
  Drawer,
  Empty,
  ErrorBar,
  KpiBar,
  Paginator,
  SearchBox,
  Stat,
  capTone,
  num,
  tint,
  useRows,
} from './kit.jsx';
import { Badge, dt, sid } from './ui.jsx';
import {
  Avatar,
  Cell2,
  DataGrid,
  Facts,
  PAGE_SIZE,
  ScreenHead,
  Toolbar,
  downloadCsv,
  fmtBytes,
  indexBy,
  useCall,
  useDebounced,
} from './dataKit.jsx';

const PATH = '/api/v1/admin/vpn-accounts';
const EXPORT_CAP = 2000;

const usage = (a) =>
  a.traffic_limit_bytes ? Math.min(1, Number(a.traffic_used_bytes || 0) / a.traffic_limit_bytes) : null;
const daysText = (a) =>
  a.days_left == null ? 'نامحدود' : a.health === 'expired' ? 'منقضی شده' : `${num(a.days_left)} روز مانده`;

function Traffic({ a, wide }) {
  const u = usage(a);
  return (
    <span className={`block ${wide ? '' : 'min-w-[9rem]'}`}>
      <span className="num block text-[12px] font-bold">
        {fmtBytes(a.traffic_used_bytes)}{' '}
        <span className="font-normal text-[var(--mu)]">/ {u == null ? '∞' : fmtBytes(a.traffic_limit_bytes)}</span>
      </span>
      {u != null && <Bar value={u} tone={capTone(u)} label={`مصرف ترافیک ${Math.round(u * 100)}٪`} />}
    </span>
  );
}

export default function VpnAccountsView({ api, toast }) {
  const call = useCall(api);
  const stores = useRows(call, '/api/v1/admin/stores');
  const [q, setQ] = useState('');
  const [state, setState] = useState('all');
  const [store, setStore] = useState('all');
  const [page, setPage] = useState(0);
  const [tick, setTick] = useState(0);
  const [selId, setSelId] = useState(null);
  const [res, setRes] = useState({ key: null, rows: [], total: 0, failed: false });
  const [cnt, setCnt] = useState(null);
  const dq = useDebounced(q, 300);
  const storeMap = useMemo(() => indexBy(stores.rows), [stores.rows]);
  const storeName = (id) => storeMap[id]?.name || sid(id);

  const key = `${dq}|${state}|${store}|${page}|${tick}`;
  const loading = res.key !== key;

  const query = (extra = {}) => {
    const p = new URLSearchParams({ limit: String(PAGE_SIZE), offset: '0', ...extra });
    if (dq.trim()) p.set('q', dq.trim());
    if (state !== 'all') p.set('state', state);
    if (store !== 'all') p.set('store_id', store);
    return p;
  };

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await call(`${PATH}?${query({ offset: String(page * PAGE_SIZE) })}`);
        if (!r.ok) throw new Error(String(r.status));
        const rows = await r.json();
        if (alive) setRes({ key, rows, total: Number(r.headers.get('X-Total-Count')) || rows.length, failed: false });
      } catch {
        if (alive) setRes({ key, rows: [], total: 0, failed: true });
      }
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [call, key]);

  // KPI counters follow the store filter only (not the text search or the state chip).
  useEffect(() => {
    let alive = true;
    const total = async (st) => {
      const p = new URLSearchParams({ limit: '1' });
      if (st) p.set('state', st);
      if (store !== 'all') p.set('store_id', store);
      const r = await call(`${PATH}?${p}`);
      if (!r.ok) throw new Error(String(r.status));
      return Number(r.headers.get('X-Total-Count')) || 0;
    };
    Promise.all([total(''), total('active'), total('expiring'), total('expired')])
      .then(([all, active, expiring, expired]) => alive && setCnt({ all, active, expiring, expired }))
      .catch(() => alive && setCnt(null));
    return () => {
      alive = false;
    };
  }, [call, store, tick]);

  const reset = (setter) => (v) => {
    setter(v);
    setPage(0);
  };
  const pickState = (s) => reset(setState)(state === s ? 'all' : s);
  const sel = res.rows.find((a) => a.id === selId) || null;
  const filtersOn = state !== 'all' || store !== 'all' || q.trim() !== '';

  const exportCsv = async () => {
    try {
      const out = [];
      for (let off = 0; off < EXPORT_CAP; off += 200) {
        const r = await call(`${PATH}?${query({ limit: '200', offset: String(off) })}`);
        if (!r.ok) throw new Error(String(r.status));
        const rows = await r.json();
        out.push(...rows);
        if (rows.length < 200) break;
      }
      downloadCsv(
        'vpn-accounts',
        [
          'نام کاربری',
          'مشتری',
          'فروشگاه',
          'وضعیت',
          'روز باقی‌مانده',
          'انقضا',
          'ترافیک مصرفی (بایت)',
          'سقف ترافیک (بایت)',
        ],
        out.map((a) => [
          a.username,
          a.customer_name,
          storeName(a.store_id),
          a.health,
          a.days_left ?? '',
          a.expires_at ?? '',
          a.traffic_used_bytes,
          a.traffic_limit_bytes ?? '',
        ]),
      );
    } catch {
      toast('دریافت خروجی ناموفق بود');
    }
  };

  const columns = [
    {
      key: 'customer',
      label: 'مشتری',
      render: (a) => (
        <span className="flex items-center gap-2.5">
          <Avatar name={a.customer_name} />
          <Cell2 main={a.customer_name} sub={storeName(a.store_id)} />
        </span>
      ),
    },
    {
      key: 'username',
      label: 'نام اکانت',
      render: (a) => (
        <span className="num font-bold" dir="ltr">
          {a.username}
        </span>
      ),
    },
    { key: 'health', label: 'وضعیت', render: (a) => <Badge s={a.health || a.status} /> },
    {
      key: 'exp',
      label: 'اعتبار',
      render: (a) => (
        <Cell2
          main={daysText(a)}
          sub={a.expires_at ? new Date(a.expires_at).toLocaleDateString('fa-IR', { dateStyle: 'medium' }) : ''}
        />
      ),
    },
    { key: 'traffic', label: 'ترافیک', render: (a) => <Traffic a={a} /> },
  ];

  return (
    <div className="space-y-4">
      <ScreenHead
        title="اکانت‌های VPN"
        count={cnt?.all}
        hint="همه اکانت‌های همه فروشگاه‌ها؛ جستجو بر اساس نام اکانت، نام یا ایمیل مشتری."
        onRefresh={() => setTick((t) => t + 1)}
        busy={loading}
        onExport={exportCsv}
        exportDisabled={!res.total}
      />
      <KpiBar cols={4}>
        <Stat
          Icon={Server}
          tone="in"
          label="همه اکانت‌ها"
          value={cnt?.all}
          active={state === 'all'}
          onClick={() => reset(setState)('all')}
        />
        <Stat
          Icon={ShieldCheck}
          tone="ok"
          label="فعال"
          value={cnt?.active}
          active={state === 'active'}
          onClick={() => pickState('active')}
        />
        <Stat
          Icon={Timer}
          tone={cnt?.expiring ? 'wn' : 'mu'}
          label="در آستانه انقضا"
          sub="کمتر از ۳ روز"
          value={cnt?.expiring}
          active={state === 'expiring'}
          onClick={() => pickState('expiring')}
        />
        <Stat
          Icon={ShieldOff}
          tone={cnt?.expired ? 'bd' : 'mu'}
          label="منقضی"
          value={cnt?.expired}
          active={state === 'expired'}
          onClick={() => pickState('expired')}
        />
      </KpiBar>
      <Toolbar>
        <SearchBox value={q} onChange={reset(setQ)} label="جستجوی اکانت" placeholder="نام اکانت، نام یا ایمیل مشتری…" />
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
        {filtersOn && (
          <button
            className="btn btn-g !py-2 !text-xs"
            onClick={() => {
              setQ('');
              setState('all');
              setStore('all');
              setPage(0);
            }}
          >
            پاک‌کردن فیلترها
          </button>
        )}
      </Toolbar>
      {res.failed && !loading && <ErrorBar onRetry={() => setTick((t) => t + 1)}>دریافت اکانت‌ها ناموفق بود.</ErrorBar>}
      <DataGrid
        caption="فهرست اکانت‌های VPN"
        columns={columns}
        rows={res.rows}
        loading={loading}
        onRowClick={(a) => setSelId(a.id)}
        emptyNode={
          <Empty
            Icon={Gauge}
            title={filtersOn ? 'اکانتی با این فیلتر پیدا نشد' : 'هنوز اکانتی ساخته نشده'}
            text={
              filtersOn
                ? 'عبارت جستجو یا فیلترها را تغییر دهید.'
                : 'اکانت‌ها پس از تکمیل اولین سفارش اینجا نمایش داده می‌شوند.'
            }
          />
        }
      />
      <Paginator page={page} setPage={setPage} total={res.total} pageSize={PAGE_SIZE} />
      {sel && <AccountDrawer a={sel} store={storeName(sel.store_id)} onClose={() => setSelId(null)} />}
    </div>
  );
}

function AccountDrawer({ a, store, onClose }) {
  const u = usage(a);
  return (
    <Drawer
      title={a.username}
      subtitle={`${a.customer_name || '—'} · ${store}`}
      icon={
        <span
          className="tile h-10 w-10"
          style={tint(a.health === 'active' ? 'ok' : a.health === 'expiring' ? 'wn' : 'bd')}
        >
          <Server size={19} />
        </span>
      }
      onClose={onClose}
    >
      <div className="card space-y-3 p-4">
        <div className="flex items-center justify-between gap-3">
          <Badge s={a.health || a.status} />
          <span className="text-xs font-bold text-[var(--mu)]">
            <Clock size={12} className="ml-1 inline" />
            {daysText(a)}
          </span>
        </div>
        <Traffic a={a} wide />
        {u != null && (
          <p className="text-[11px] text-[var(--mu)]">{num(Math.round(u * 100))}٪ از سقف ترافیک مصرف شده است.</p>
        )}
      </div>
      <Facts
        items={[
          { label: 'نام اکانت', value: a.username, ltr: true, copy: true },
          { label: 'مشتری', value: a.customer_name },
          { label: 'فروشگاه', value: store },
          { label: 'وضعیت پنل', value: a.status },
          { label: 'انقضا', value: a.expires_at ? dt(a.expires_at) : 'نامحدود' },
          { label: 'ترافیک مصرفی', value: fmtBytes(a.traffic_used_bytes) },
          { label: 'سقف ترافیک', value: a.traffic_limit_bytes ? fmtBytes(a.traffic_limit_bytes) : 'نامحدود' },
          { label: 'شناسه اکانت', value: a.id, ltr: true, copy: true },
          { label: 'شناسه مشتری', value: a.user_id, ltr: true, copy: true },
        ]}
      />
    </Drawer>
  );
}
