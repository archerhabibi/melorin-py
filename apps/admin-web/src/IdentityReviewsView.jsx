// «بررسی هویت» — queue of identity-link conflicts (verified email / Google / Telegram account that already belongs
// to another user). Core never merges such accounts automatically; the admin reads both sides and decides here.
import { useMemo, useState } from 'react';
import {
  ArrowLeftRight,
  CheckCircle2,
  Clock,
  Fingerprint,
  Globe,
  Inbox,
  Mail,
  RotateCcw,
  Send,
  ShieldAlert,
  ShieldCheck,
  UserRound,
  Users,
} from 'lucide-react';
import { authFetch } from './api.js';
import { dt, sid } from './ui.jsx';
import {
  Drawer,
  Empty,
  ErrorBar,
  Field,
  KpiBar,
  Pills,
  SearchBox,
  SortSelect,
  Stat,
  errText,
  num,
  tint,
  useRows,
} from './kit.jsx';

const PROVIDERS = {
  google: { label: 'Google', Icon: Globe, tone: 'in' },
  email: { label: 'ایمیل', Icon: Mail, tone: 'wn' },
  telegram: { label: 'تلگرام', Icon: Send, tone: 'ok' },
};
const REASONS = {
  verified_email_matches_other_user: [
    'ایمیل تأییدشده متعلق به حساب دیگری است',
    'کاربر ایمیلی را تأیید کرد که از قبل به یک حساب دیگر وصل است.',
  ],
  google_account_belongs_to_other_user: [
    'حساب Google متعلق به کاربر دیگری است',
    'کاربر خواست حساب Google ای را وصل کند که قبلاً به حساب دیگری گره خورده است.',
  ],
  multiple_verified_email_users: [
    'ایمیل با چند حساب هم‌پوشانی دارد',
    'ایمیل ورودی با بیش از یک حساب موجود مطابقت دارد؛ اتصال خودکار ممکن نبود.',
  ],
  email_field_conflict: [
    'ایمیل قبلاً روی پروفایل دیگری ثبت شده',
    'ایمیل در پروفایل یک حساب قدیمی ثبت است، بدون اینکه هویت متصل داشته باشد.',
  ],
};
const reasonOf = (r) => REASONS[r] || [r || 'نامشخص', 'دلیل ثبت‌شده توسط Core.'];
const prov = (p) => PROVIDERS[p] || { label: p || '—', Icon: Fingerprint, tone: 'mu' };
const STRIPE = { open: 'var(--wn)', dismissed: 'var(--ln)', linked: 'var(--ok)' };
const STATUS_TEXT = { open: 'باز', dismissed: 'رد شده', linked: 'متصل شده' };
const ago = (v) => {
  if (!v) return '—';
  const m = Math.max(0, Math.round((Date.now() - new Date(v).getTime()) / 60000));
  if (m < 1) return 'همین الان';
  if (m < 60) return `${num(m)} دقیقه پیش`;
  if (m < 1440) return `${num(Math.round(m / 60))} ساعت پیش`;
  return `${num(Math.round(m / 1440))} روز پیش`;
};

function ProviderTile({ p }) {
  const { Icon, tone } = prov(p);
  return (
    <span className="tile" style={{ width: 44, height: 44, ...tint(tone) }}>
      <Icon size={19} />
    </span>
  );
}
const STATUS_TONE = { open: 'b-wn', dismissed: 'b-mu', linked: 'b-ok' };
const StatusBadge = ({ s }) => <span className={`badge ${STATUS_TONE[s] || 'b-mu'}`}>{STATUS_TEXT[s] || s}</span>;

/** Compact account card used on both sides of a conflict. */
function UserCard({ u, role, fallbackId }) {
  if (!u)
    return (
      <div className="rounded-xl border border-dashed border-[var(--ln)] p-3 text-xs text-[var(--mu)]">
        {role}: حساب <span dir="ltr">{sid(fallbackId)}</span> پیدا نشد (ممکن است حذف شده باشد).
      </div>
    );
  return (
    <div className="min-w-0 rounded-xl border border-[var(--hair)] bg-[var(--sf2)] p-3">
      <div className="flex items-center gap-2">
        <span className="tile h-8 w-8 bg-[var(--mb)] text-[var(--mu)]">
          <UserRound size={15} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[11px] font-bold text-[var(--mu)]">{role}</div>
          <div className="truncate text-sm font-extrabold">{u.display_name || 'بدون نام'}</div>
        </div>
        {u.is_guest && <span className="badge b-mu">مهمان</span>}
        {!u.is_active && <span className="badge b-bd">غیرفعال</span>}
      </div>
      <dl className="mt-2.5 grid grid-cols-2 gap-x-3 gap-y-1.5 text-[11px]">
        <dt className="text-[var(--mu)]">ایمیل</dt>
        <dd className="truncate font-bold" dir="ltr" style={{ textAlign: 'right' }}>
          {u.email || '—'}
        </dd>
        <dt className="text-[var(--mu)]">سفارش‌ها</dt>
        <dd className="num font-bold">{num(u.orders)}</dd>
        <dt className="text-[var(--mu)]">عضویت</dt>
        <dd className="font-bold">{ago(u.created_at)}</dd>
        <dt className="text-[var(--mu)]">روش‌های ورود</dt>
        <dd className="flex flex-wrap gap-1">
          {u.providers.length
            ? u.providers.map((p) => (
                <span key={p} className="spec !px-1.5 !py-0.5 !text-[10px]">
                  {prov(p).label}
                </span>
              ))
            : '—'}
        </dd>
      </dl>
    </div>
  );
}

/** Hint that tells the admin how risky the decision is: an account with orders must never be thrown away blindly. */
function Advice({ r }) {
  const heavy = (r.candidates || []).some((c) => c.orders > 0) || (r.source_user?.orders || 0) > 0;
  return (
    <p
      className={`flex items-start gap-2 rounded-xl p-3 text-xs leading-6 ${heavy ? 'bg-[var(--wnb)] text-[var(--wn)]' : 'bg-[var(--inb)] text-[var(--in)]'}`}
    >
      {heavy ? (
        <ShieldAlert size={16} className="mt-0.5 flex-none" />
      ) : (
        <ShieldCheck size={16} className="mt-0.5 flex-none" />
      )}
      <span>
        {heavy
          ? 'حداقل یکی از این حساب‌ها سفارش دارد. تا مطمئن نشده‌اید هر دو حساب مال یک نفر است، ادغام یا رد نکنید؛ در صورت شک با کاربر از طریق تیکت تماس بگیرید.'
          : 'هیچ‌کدام از حساب‌ها سفارشی ندارند؛ ریسک از دست رفتن اطلاعات پایین است. اگر هر دو حساب مال یک نفر نیستند، می‌توانید درخواست را رد کنید.'}
      </span>
    </p>
  );
}

function ReviewCard({ r, onOpen, onQuick }) {
  const [title] = reasonOf(r.reason);
  return (
    <article
      className="card card-i stripe rise cursor-pointer p-4 sm:p-5"
      style={{ '--stripe': STRIPE[r.status] || 'var(--ln)' }}
      onClick={() => onOpen(r)}
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onOpen(r)}
      aria-label={`بررسی ${r.email || 'حساب'}`}
    >
      <div className="flex flex-wrap items-center gap-3">
        <ProviderTile p={r.provider} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-extrabold" dir="ltr" style={{ textAlign: 'right' }}>
            {r.email || 'بدون ایمیل'}
          </div>
          <div className="mt-0.5 text-xs text-[var(--mu)]">{title}</div>
        </div>
        <div className="flex items-center gap-2">
          <span className="spec">
            <Clock size={12} />
            {ago(r.created_at)}
          </span>
          <StatusBadge s={r.status} />
        </div>
      </div>
      <div className="mt-4 grid items-center gap-2 md:grid-cols-[1fr_auto_1fr]">
        <UserCard u={r.source_user} role="حساب درخواست‌دهنده" fallbackId={r.source_user_id} />
        <span className="mx-auto grid h-8 w-8 place-items-center rounded-full bg-[var(--mb)] text-[var(--mu)] max-md:rotate-90">
          <ArrowLeftRight size={15} />
        </span>
        <div className="grid gap-2">
          {r.candidates?.length ? (
            r.candidates.slice(0, 2).map((c) => <UserCard key={c.id} u={c} role="حساب موجود" />)
          ) : (
            <UserCard u={null} role="حساب موجود" fallbackId={r.candidate_user_ids?.[0]} />
          )}
          {r.candidates?.length > 2 && (
            <span className="text-center text-[11px] text-[var(--mu)]">+{num(r.candidates.length - 2)} حساب دیگر</span>
          )}
        </div>
      </div>
      {r.status === 'open' && (
        <div className="mt-4 flex flex-wrap items-center justify-end gap-2" onClick={(e) => e.stopPropagation()}>
          <button className="btn btn-g" onClick={() => onQuick(r)}>
            رد سریع
          </button>
          <button className="btn !py-1.5 !text-xs" onClick={() => onOpen(r)}>
            <Fingerprint size={14} />
            بررسی و تصمیم
          </button>
        </div>
      )}
      {r.status === 'dismissed' && r.resolution_note && (
        <p className="mt-3 rounded-lg bg-[var(--mb)] p-2.5 text-xs leading-6 text-[var(--mu)]">
          یادداشت ادمین: {r.resolution_note}
        </p>
      )}
    </article>
  );
}

function ReviewDrawer({ r, call, toast, onClose, onDone }) {
  const [note, setNote] = useState(r.resolution_note || '');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [why, explain] = reasonOf(r.reason);
  const run = async (kind) => {
    setBusy(true);
    setErr('');
    try {
      const res = await call(`/api/v1/admin/identity-link-reviews/${r.id}/${kind}`, {
        method: 'POST',
        ...(kind === 'dismiss' ? { body: JSON.stringify({ note: note.trim() || null }) } : {}),
      });
      if (!res.ok) {
        setErr(await errText(res, 'عملیات ناموفق بود'));
        return;
      }
      toast(kind === 'dismiss' ? 'درخواست رد شد' : 'به صف باز برگشت');
      onDone();
    } catch {
      setErr('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy(false);
    }
  };
  const open = r.status === 'open';
  return (
    <Drawer
      title="بررسی تعارض هویت"
      subtitle={r.email || 'بدون ایمیل'}
      icon={<ProviderTile p={r.provider} />}
      dirty={open && note.trim() !== (r.resolution_note || '')}
      busy={busy}
      error={err}
      onClose={onClose}
      footer={
        open ? (
          <button className="btn !bg-[var(--bd)] !text-white" disabled={busy} onClick={() => run('dismiss')}>
            رد درخواست
          </button>
        ) : r.status === 'dismissed' ? (
          <button className="btn" disabled={busy} onClick={() => run('reopen')}>
            <RotateCcw size={14} />
            بازگرداندن به صف
          </button>
        ) : null
      }
    >
      <section className="card space-y-3 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge s={r.status} />
          <span className="spec">{prov(r.provider).label}</span>
          <span className="spec">
            <Clock size={12} />
            {dt(r.created_at)}
          </span>
        </div>
        <h3 className="text-sm font-extrabold">{why}</h3>
        <p className="text-xs leading-6 text-[var(--mu)]">{explain}</p>
      </section>
      <Advice r={r} />
      <section className="grid gap-3 sm:grid-cols-2">
        <UserCard u={r.source_user} role="حساب درخواست‌دهنده" fallbackId={r.source_user_id} />
        <div className="grid gap-3">
          {r.candidates?.length ? (
            r.candidates.map((c) => <UserCard key={c.id} u={c} role="حساب موجود" />)
          ) : (
            <UserCard u={null} role="حساب موجود" fallbackId={r.candidate_user_ids?.[0]} />
          )}
        </div>
      </section>
      <section className="card space-y-3 p-4">
        <Field label="یادداشت ادمین" hint="در لاگ ممیزی ثبت می‌شود (حداکثر ۵۰۰ نویسه).">
          <textarea
            className="inp min-h-24"
            maxLength={500}
            disabled={!open}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="مثلاً: با کاربر از طریق تیکت تماس گرفته شد؛ دو حساب متعلق به یک نفر نیست."
          />
        </Field>
        {r.resolved_at && <p className="text-[11px] text-[var(--mu)]">آخرین تغییر: {dt(r.resolved_at)}</p>}
      </section>
    </Drawer>
  );
}

export default function IdentityReviewsView({ api, toast }) {
  const call = (p, o = {}) => authFetch(api.base, p, o);
  const { rows, failed, load } = useRows(call, '/api/v1/admin/identity-link-reviews?status=all');
  const [status, setStatus] = useState('open');
  const [provider, setProvider] = useState('all');
  const [q, setQ] = useState('');
  const [sort, setSort] = useState('new');
  const [sel, setSel] = useState(null);

  const all = rows || [];
  const count = (f) => all.filter(f).length;
  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    const list = all.filter(
      (r) =>
        (status === 'all' || r.status === status) &&
        (provider === 'all' || r.provider === provider) &&
        (!t ||
          [
            r.email,
            r.reason,
            r.source_user?.display_name,
            r.source_user?.email,
            ...(r.candidates || []).flatMap((c) => [c.display_name, c.email]),
          ].some((x) =>
            String(x || '')
              .toLowerCase()
              .includes(t),
          )),
    );
    return list.sort((a, b) => (sort === 'new' ? -1 : 1) * (new Date(a.created_at) - new Date(b.created_at)));
  }, [all, status, provider, q, sort]);

  const quick = async (r) => {
    const res = await call(`/api/v1/admin/identity-link-reviews/${r.id}/dismiss`, { method: 'POST' });
    if (res.ok) {
      toast('درخواست رد شد');
      load();
    } else toast(await errText(res, 'ناموفق'));
  };
  const done = () => {
    setSel(null);
    load();
  };
  const current = sel && all.find((r) => r.id === sel.id);

  return (
    <div className="space-y-5">
      <KpiBar cols={4}>
        <Stat
          label="در انتظار تصمیم"
          value={count((r) => r.status === 'open')}
          tone="wn"
          Icon={Inbox}
          active={status === 'open'}
          onClick={() => setStatus('open')}
          sub="نیازمند بررسی دستی"
        />
        <Stat
          label="رد شده"
          value={count((r) => r.status === 'dismissed')}
          tone="mu"
          Icon={CheckCircle2}
          active={status === 'dismissed'}
          onClick={() => setStatus('dismissed')}
        />
        <Stat
          label="متصل شده"
          value={count((r) => r.status === 'linked')}
          tone="ok"
          Icon={Users}
          active={status === 'linked'}
          onClick={() => setStatus('linked')}
        />
        <Stat
          label="همه موارد"
          value={all.length}
          tone="in"
          Icon={Fingerprint}
          active={status === 'all'}
          onClick={() => setStatus('all')}
        />
      </KpiBar>
      <div className="tool">
        <SearchBox value={q} onChange={setQ} label="جستجو در موارد" placeholder="ایمیل، نام یا دلیل…" />
        <Pills
          label="ارائه‌دهنده"
          value={provider}
          onChange={setProvider}
          options={[
            ['all', 'همه', all.length],
            ...Object.entries(PROVIDERS).map(([k, v]) => [k, v.label, count((r) => r.provider === k)]),
          ]}
        />
        <span className="mr-auto" />
        <SortSelect
          value={sort}
          onChange={setSort}
          options={[
            ['new', 'جدیدترین'],
            ['old', 'قدیمی‌ترین'],
          ]}
        />
      </div>
      <p className="px-1 text-xs leading-6 text-[var(--mu)]">
        وقتی ایمیل یا حساب تأییدشده‌ای با حساب دیگری هم‌پوشانی دارد، سیستم هرگز حساب‌ها را خودکار ادغام نمی‌کند و مورد
        را اینجا برای تصمیم شما نگه می‌دارد.
      </p>
      {failed && <ErrorBar onRetry={load}>دریافت فهرست ناموفق بود.</ErrorBar>}
      {rows === null ? (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="skel h-44" />
          ))}
        </div>
      ) : shown.length === 0 ? (
        <Empty
          Icon={ShieldCheck}
          title={status === 'open' && !q && provider === 'all' ? 'صف بررسی خالی است' : 'موردی پیدا نشد'}
          text={
            status === 'open' && !q && provider === 'all'
              ? 'هیچ تعارض هویتی منتظر تصمیم شما نیست.'
              : 'فیلتر یا عبارت جستجو را تغییر دهید.'
          }
        />
      ) : (
        <div className="grid gap-3">
          {shown.map((r) => (
            <ReviewCard key={r.id} r={r} onOpen={setSel} onQuick={quick} />
          ))}
        </div>
      )}
      {current && (
        <ReviewDrawer
          key={current.id + current.status}
          r={current}
          call={call}
          toast={toast}
          onClose={() => setSel(null)}
          onDone={done}
        />
      )}
    </div>
  );
}
