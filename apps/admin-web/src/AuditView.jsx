// Audit screen — who did what, when. Domain filter chips, period filter, search and a detail drawer with the event payload.
// Data: GET /api/v1/admin/audit (latest 500: id, actor_id, action, entity_type, entity_id, store_id, data, ip, created_at).
import { useMemo, useState } from 'react';
import { Activity, CalendarDays, ScrollText, ShieldAlert, UserCog } from 'lucide-react';
import {
  CopyButton,
  Drawer,
  Empty,
  ErrorBar,
  KpiBar,
  Paginator,
  Pills,
  SearchBox,
  Stat,
  tint,
  useRows,
} from './kit.jsx';
import { dt, sid } from './ui.jsx';
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
  pageOf,
  useCall,
} from './dataKit.jsx';

const CAP = 500;
const DAY = 86400000;

// Persian labels for the known event domains (the part of `action` before the dot) and a few common verbs.
const DOMAINS = {
  admin: 'مدیر',
  admin_access: 'دسترسی مدیر',
  api_credential: 'کلید API',
  auth: 'احراز هویت',
  bank_sms: 'پیامک بانکی',
  bot_store_binding: 'اتصال ربات',
  broadcast: 'پیام همگانی',
  bundle: 'بسته فروش',
  bundle_product: 'محصول بسته',
  catalog: 'کاتالوگ',
  commission: 'کمیسیون',
  coupon: 'کوپن',
  email: 'ایمیل',
  event_center: 'مرکز رویداد',
  feature_flag: 'فلگ ویژگی',
  google: 'ورود گوگل',
  identity: 'هویت',
  identity_link_review: 'بررسی اتصال هویت',
  order: 'سفارش',
  panel: 'پنل',
  payment: 'پرداخت',
  system_setting: 'تنظیمات سیستم',
};
const VERBS = {
  created: 'ایجاد شد',
  updated: 'ویرایش شد',
  deleted: 'حذف شد',
  removed: 'حذف شد',
  enabled: 'فعال شد',
  disabled: 'غیرفعال شد',
  refunded: 'مسترد شد',
  completed: 'تکمیل شد',
  cancelled: 'لغو شد',
  login: 'ورود',
  sent: 'ارسال شد',
  saved: 'ذخیره شد',
  tested: 'آزمایش شد',
  rotated: 'چرخش یافت',
  manual_review: 'ارجاع به بررسی دستی',
  bank_sms_matched: 'تطبیق با پیامک بانکی',
  password_changed: 'رمز عبور تغییر کرد',
  password_change_failed: 'تغییر رمز ناموفق',
  status_changed: 'وضعیت تغییر کرد',
  source_saved: 'منبع ذخیره شد',
  token_rotated: 'توکن چرخش یافت',
  restored: 'بازیابی شد',
  ignored: 'نادیده گرفته شد',
  dismissed: 'رد شد',
  reopened: 'بازگشایی شد',
  linked: 'متصل شد',
  renewed_by_owner: 'تمدید توسط مالک',
  provisioning_failed: 'ساخت ناموفق',
};
// Never echo credentials that an event may have captured (tokens, passwords, API keys, secrets).
const SECRET_KEY = /(token|secret|password|passwd|api_?key|authorization)/i;
const redact = (v) =>
  Array.isArray(v)
    ? v.map(redact)
    : v && typeof v === 'object'
      ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, SECRET_KEY.test(k) ? '••••••' : redact(x)]))
      : v;
const domainOf = (a) => String(a || '').split('.')[0];
const domainLabel = (d) => DOMAINS[d] || d || 'نامشخص';
const actionLabel = (a) => {
  const [d, ...rest] = String(a || '').split('.');
  const v = rest.join('.');
  // Unknown verbs stay English; isolate them so they do not scramble the Persian word order around them.
  return v ? `${domainLabel(d)} · ${VERBS[v] || `\u2066${v.replace(/_/g, ' ')}\u2069`}` : domainLabel(d);
};
// Events that deserve a second look: money going back, failures, credentials and access changes.
const SENSITIVE = /(refund|failed|deleted|removed|rotated|password|api_credential|admin_access|token)/;
const isSensitive = (e) => SENSITIVE.test(e.action || '');

const PERIODS = [
  ['all', 'همه زمان‌ها', Infinity],
  ['day', '۲۴ ساعت اخیر', DAY],
  ['week', '۷ روز اخیر', 7 * DAY],
  ['month', '۳۰ روز اخیر', 30 * DAY],
];

export default function AuditView({ api }) {
  const call = useCall(api);
  const audit = useRows(call, '/api/v1/admin/audit');
  const users = useRows(call, '/api/v1/admin/users');
  const stores = useRows(call, '/api/v1/admin/stores');
  const [domain, setDomain] = useState('all');
  const [period, setPeriod] = useState('all');
  const [onlySens, setOnlySens] = useState(false);
  const [q, setQ] = useState('');
  const [page, setPage] = useState(0);
  const [selId, setSelId] = useState(null);

  const userMap = useMemo(() => indexBy(users.rows), [users.rows]);
  const storeMap = useMemo(() => indexBy(stores.rows), [stores.rows]);
  const loading = audit.rows === null;
  const all = useMemo(() => audit.rows || [], [audit.rows]);
  const actor = (e) =>
    e.actor_id ? userMap[e.actor_id]?.display_name || userMap[e.actor_id]?.email || sid(e.actor_id) : 'سیستم';

  const domainCounts = useMemo(() => {
    const m = {};
    all.forEach((e) => {
      const d = domainOf(e.action);
      m[d] = (m[d] || 0) + 1;
    });
    return Object.entries(m).sort((a, b) => b[1] - a[1]);
  }, [all]);

  const stats = useMemo(() => {
    const now = Date.now();
    return {
      day: all.filter((e) => now - new Date(e.created_at).getTime() < DAY).length,
      sens: all.filter(isSensitive).length,
      actors: new Set(all.map((e) => e.actor_id).filter(Boolean)).size,
    };
  }, [all]);

  const filtered = useMemo(() => {
    const lim = PERIODS.find((p) => p[0] === period)[2];
    const now = Date.now();
    return all
      .filter((e) => domain === 'all' || domainOf(e.action) === domain)
      .filter((e) => !onlySens || isSensitive(e))
      .filter((e) => lim === Infinity || now - new Date(e.created_at).getTime() < lim)
      .filter((e) => matches(q, e.action, actionLabel(e.action), actor(e), e.entity_type, e.entity_id, e.ip));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [all, domain, period, onlySens, q, userMap]);
  const shown = pageOf(filtered, page);
  const sel = all.find((e) => e.id === selId) || null;
  const reset = (setter) => (v) => {
    setter(v);
    setPage(0);
  };
  const filtersOn = domain !== 'all' || period !== 'all' || onlySens || q.trim() !== '';

  const exportCsv = () =>
    downloadCsv(
      'audit',
      ['زمان', 'عملیات', 'کد عملیات', 'عامل', 'موجودیت', 'شناسه موجودیت', 'IP'],
      filtered.map((e) => [
        e.created_at,
        actionLabel(e.action),
        e.action,
        actor(e),
        e.entity_type || '',
        e.entity_id || '',
        e.ip || '',
      ]),
    );

  const columns = [
    { key: 'at', label: 'زمان', render: (e) => <When v={e.created_at} /> },
    {
      key: 'action',
      label: 'عملیات',
      m: 'title',
      render: (e) => (
        <span className="flex items-center gap-2">
          {isSensitive(e) && <ShieldAlert size={14} className="shrink-0 text-[var(--wn)]" aria-label="عملیات حساس" />}
          <Cell2 main={actionLabel(e.action)} sub={e.action} dir="ltr" />
        </span>
      ),
    },
    { key: 'actor', label: 'عامل', render: (e) => <span className="text-[13px]">{actor(e)}</span> },
    {
      key: 'entity',
      label: 'موجودیت',
      render: (e) => <Cell2 main={e.entity_type || ''} sub={e.entity_id ? sid(e.entity_id) : ''} dir="ltr" />,
    },
    {
      key: 'ip',
      label: 'IP',
      render: (e) => (
        <span className="num text-xs text-[var(--mu)]" dir="ltr">
          {e.ip || '—'}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <ScreenHead
        title="ممیزی"
        count={all.length}
        hint="ثبت تغییرات و عملیات مهم سیستم؛ روی هر رویداد بزنید تا جزئیات کامل را ببینید."
        onRefresh={audit.load}
        busy={loading}
        onExport={exportCsv}
        exportDisabled={!filtered.length}
      />
      <KpiBar cols={4}>
        <Stat
          Icon={ScrollText}
          tone="in"
          label="کل رویدادها"
          value={all.length}
          active={!filtersOn}
          onClick={() => {
            setDomain('all');
            setPeriod('all');
            setOnlySens(false);
            setQ('');
            setPage(0);
          }}
        />
        <Stat
          Icon={CalendarDays}
          tone="ok"
          label="۲۴ ساعت اخیر"
          value={stats.day}
          active={period === 'day'}
          onClick={() => reset(setPeriod)(period === 'day' ? 'all' : 'day')}
        />
        <Stat
          Icon={ShieldAlert}
          tone={stats.sens ? 'wn' : 'mu'}
          label="عملیات حساس"
          value={stats.sens}
          active={onlySens}
          onClick={() => reset(setOnlySens)(!onlySens)}
        />
        <Stat Icon={UserCog} tone="in" label="عامل‌های فعال" value={stats.actors} />
      </KpiBar>
      <Toolbar>
        <SearchBox
          value={q}
          onChange={reset(setQ)}
          hotkey
          label="جستجوی ممیزی"
          placeholder="عملیات، عامل، شناسه یا IP…"
        />
        <select
          aria-label="بازه زمانی"
          className="inp !w-auto !py-2 !text-xs font-bold"
          value={period}
          onChange={(e) => reset(setPeriod)(e.target.value)}
        >
          {PERIODS.map(([k, l]) => (
            <option key={k} value={k}>
              {l}
            </option>
          ))}
        </select>
        {filtersOn && (
          <button
            className="btn btn-g !py-2 !text-xs"
            onClick={() => {
              setDomain('all');
              setPeriod('all');
              setOnlySens(false);
              setQ('');
              setPage(0);
            }}
          >
            پاک‌کردن فیلترها
          </button>
        )}
      </Toolbar>
      {domainCounts.length > 1 && (
        <Pills
          scroll
          label="گروه رویداد"
          value={domain}
          onChange={reset(setDomain)}
          options={[['all', 'همه', all.length], ...domainCounts.slice(0, 10).map(([d, n]) => [d, domainLabel(d), n])]}
        />
      )}
      {audit.failed && <ErrorBar onRetry={audit.load}>دریافت لاگ ممیزی ناموفق بود.</ErrorBar>}
      <DataGrid
        caption="لاگ ممیزی"
        columns={columns}
        rows={shown}
        loading={loading}
        onRowClick={(e) => setSelId(e.id)}
        emptyNode={
          <Empty
            Icon={Activity}
            title={filtersOn ? 'رویدادی با این فیلتر پیدا نشد' : 'هنوز رویدادی ثبت نشده'}
            text={
              filtersOn
                ? 'عبارت جستجو، بازه زمانی یا گروه رویداد را تغییر دهید.'
                : 'عملیات مدیران و سیستم پس از انجام اینجا ثبت می‌شود.'
            }
          />
        }
      />
      <Paginator page={page} setPage={setPage} total={filtered.length} pageSize={PAGE_SIZE} />
      {all.length >= CAP && (
        <p className="text-center text-[11px] text-[var(--mu)]">
          فقط {CAP.toLocaleString('fa-IR')} رویداد اخیر نمایش داده می‌شود.
        </p>
      )}
      {sel && (
        <EventDrawer e={sel} actor={actor(sel)} store={storeMap[sel.store_id]?.name} onClose={() => setSelId(null)} />
      )}
    </div>
  );
}

function EventDrawer({ e, actor, store, onClose }) {
  const payload = e.data && Object.keys(e.data).length ? JSON.stringify(redact(e.data), null, 2) : '';
  return (
    <Drawer
      title={actionLabel(e.action)}
      subtitle={dt(e.created_at)}
      icon={
        <span className="tile h-10 w-10" style={tint(isSensitive(e) ? 'wn' : 'in')}>
          <ScrollText size={19} />
        </span>
      }
      onClose={onClose}
    >
      {isSensitive(e) && (
        <p className="flex items-start gap-2 rounded-xl bg-[var(--wnb)] p-3 text-xs leading-6 text-[var(--wn)]">
          <ShieldAlert size={15} className="mt-0.5 shrink-0" />
          این رویداد جزو عملیات حساس (مالی، خطا، کلیدها یا دسترسی) است.
        </p>
      )}
      <Facts
        items={[
          { label: 'کد عملیات', value: e.action, ltr: true, copy: true },
          { label: 'عامل', value: actor },
          { label: 'موجودیت', value: e.entity_type, ltr: true },
          { label: 'شناسه موجودیت', value: e.entity_id, ltr: true, copy: true },
          { label: 'فروشگاه', value: store },
          { label: 'IP', value: e.ip, ltr: true, copy: true },
          { label: 'زمان', value: dt(e.created_at) },
          { label: 'شناسه رویداد', value: e.id, ltr: true, copy: true },
        ]}
      />
      <section className="card p-4">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-[13px] font-extrabold">داده رویداد</h3>
          {payload && <CopyButton text={payload} label="کپی داده" />}
        </div>
        {payload ? (
          <pre className="max-h-72 overflow-auto rounded-xl bg-[var(--sf2)] p-3 text-[11px] leading-5" dir="ltr">
            {payload}
          </pre>
        ) : (
          <p className="text-xs text-[var(--mu)]">داده اضافه‌ای برای این رویداد ثبت نشده است.</p>
        )}
      </section>
    </Drawer>
  );
}
