// PasarGuard admins (Operator) of every store - one per (panel, store). The desk shows their health, edits the optional
// "Profile & contact", reveals the login (audited) and works through the reseller change requests (apply / reject).
import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  ExternalLink,
  Inbox,
  KeyRound,
  Pencil,
  RefreshCw,
  Store,
  UserCog,
  XCircle,
} from 'lucide-react';
import { authFetch } from './api.js';
import { Badge, confirmDialog, dt } from './ui.jsx';
import SubBrandingCard from './SubBrandingCard.jsx';
import {
  CopyButton,
  Drawer,
  Empty,
  ErrorBar,
  Field,
  KpiBar,
  Pills,
  SearchBox,
  Segmented,
  Stat,
  digits,
  errText,
  num,
  useRows,
} from './kit.jsx';

// key, label, hint, adminOnly - the same six fields as Core's PROFILE_FIELDS (a reseller may only ask for the first four)
export const FIELDS = [
  ['profile_title', 'عنوان پروفایل', 'نام نمایشی ادمین در صفحهٔ اشتراک مشتری.', false],
  ['support_url', 'لینک پشتیبانی', 'آدرس https://… یا tg://… ؛ خالی‌گذاشتن آن را پاک می‌کند.', false],
  ['telegram_id', 'آیدی عددی تلگرام', 'فقط عدد. پس از ثبت فقط قابل تغییر است و پاک نمی‌شود.', false],
  [
    'discord_webhook',
    'وبهوک دیسکورد',
    'فقط آدرس https://discord.com/api/webhooks/… ؛ خالی‌گذاشتن آن را پاک می‌کند.',
    false,
  ],
  ['sub_domain', 'دامنهٔ اشتراک', 'فقط ادمین. آدرس لینک‌های اشتراک مشتریان را عوض می‌کند.', true],
  ['note', 'یادداشت داخلی', 'فقط ادمین. هرگز به نماینده نمایش داده نمی‌شود.', true],
];
const LABEL = Object.fromEntries(FIELDS.map(([k, l]) => [k, l]));
const shown = (v) => (v === undefined || v === null || v === '' ? '—' : String(v));
const ltr = (v) => (
  <span dir="ltr" className="latin break-all text-xs">
    {shown(v)}
  </span>
);

const STATUS_PILLS = [
  ['all', 'همه'],
  ['active', 'فعال'],
  ['pending', 'در حال راه‌اندازی'],
  ['error', 'خطا'],
  ['unsynced', 'پروفایل همگام نشده'],
];
const REQUEST_PILLS = [
  ['pending', 'در انتظار'],
  ['applied', 'اعمال‌شده'],
  ['rejected', 'رد‌شده'],
  ['cancelled', 'لغو‌شده'],
  ['all', 'همه'],
];

const KindBadge = ({ kind }) =>
  kind === 'main' ? <span className="badge b-in">فروشگاه اصلی</span> : <span className="badge b-mu">نماینده</span>;

/** POST/PATCH helper shared by both drawers: resolves to the parsed body, or null after putting the reason in `setError`. */
function useCall(call, toast) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const run = async (path, method, body, okMsg) => {
    setBusy(true);
    setError('');
    try {
      const r = await call(path, { method, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
      if (!r.ok) {
        setError(await errText(r, 'عملیات ناموفق بود'));
        return null;
      }
      const d = await r.json().catch(() => ({}));
      if (okMsg) toast(okMsg);
      return d;
    } catch {
      setError('ارتباط با سرور برقرار نشد');
      return null;
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, setError, run };
}

function AdminDrawer({ row, call, toast, onClose, onDone }) {
  const { busy, error, run } = useCall(call, toast);
  const init = useMemo(
    () => Object.fromEntries(FIELDS.map(([k]) => [k, row.profile?.[k] == null ? '' : String(row.profile[k])])),
    [row],
  );
  const [form, setForm] = useState(init);
  const [cred, setCred] = useState(null);
  // an emptied Telegram ID is "unchanged": Core and the panel cannot clear it, so it is never sent
  const changed = FIELDS.map(([k]) => k).filter(
    (k) => form[k].trim() !== init[k] && !(k === 'telegram_id' && !form[k].trim()),
  );
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  useEffect(() => {
    if (!cred) return undefined;
    const t = setTimeout(() => setCred(null), 60000); // a shown password does not stay on the screen
    return () => clearTimeout(t);
  }, [cred]);

  const save = async () => {
    const profile = Object.fromEntries(changed.map((k) => [k, k === 'telegram_id' ? Number(form[k]) : form[k].trim()]));
    const d = await run('/api/v1/admin/panel-admins/profile', 'PATCH', {
      store_id: row.store_id,
      panel_id: row.panel_id,
      profile,
    });
    if (!d) return;
    const bad = (d.results || []).find((x) => !x.synced);
    toast(
      bad
        ? `ذخیره شد، ولی هنوز روی پنل اعمال نشده؛ تلاش خودکار ادامه دارد${bad.error ? ` (${bad.error})` : ''}`
        : 'پروفایل ذخیره و روی پنل اعمال شد',
    );
    onDone();
  };
  const reveal = async () => {
    if (
      !(await confirmDialog('رمز این ادمین نمایش داده می‌شود و این دسترسی در ممیزی ثبت می‌گردد.', {
        title: 'نمایش اطلاعات ورود',
        ok: 'نمایش',
      }))
    )
      return;
    const d = await run(`/api/v1/admin/panel-admins/${row.id}/credentials`, 'GET');
    if (d) setCred(d);
  };
  const reset = async () => {
    if (
      !(await confirmDialog(`رمز «${row.username}» روی پنل عوض می‌شود و رمز قبلی از کار می‌افتد.`, {
        title: 'ساخت رمز جدید',
        danger: true,
        ok: 'ساخت رمز جدید',
      }))
    )
      return;
    const d = await run(`/api/v1/admin/panel-admins/${row.id}/reset-password`, 'POST', {}, 'رمز جدید ساخته شد');
    if (d) setCred({ ...(cred || {}), username: d.username, password: d.password, panel_url: cred?.panel_url });
  };

  return (
    <Drawer
      title={row.username}
      subtitle={`${row.store_name || '—'} · ${row.panel_name || '—'}`}
      icon={
        <span className="tile h-10 w-10 bg-[var(--inb)] text-[var(--in)]">
          <UserCog size={19} />
        </span>
      }
      dirty={changed.length > 0}
      busy={busy}
      error={error}
      onClose={onClose}
      footer={
        <button className="btn !py-2 !text-sm" disabled={busy || changed.length === 0} onClick={save}>
          <Pencil size={15} />
          ذخیرهٔ پروفایل
        </button>
      }
    >
      <section className="card p-4">
        <h4 className="mb-1 text-[13px] font-extrabold">وضعیت</h4>
        {[
          [
            'فروشگاه',
            <span key="s" className="inline-flex items-center gap-2">
              {row.store_name}
              <KindBadge kind={row.store_kind} />
            </span>,
          ],
          ['پنل', row.panel_name],
          [
            'نام کاربری',
            <span key="u" className="inline-flex items-center gap-1.5">
              {ltr(row.username)}
              <CopyButton text={row.username} label="کپی نام کاربری" />
            </span>,
          ],
          ['نقش', ltr(row.role)],
          ['وضعیت', <Badge key="b" s={row.status} />],
          ['آخرین همگام‌سازی', dt(row.synced_at)],
          ['اکانت‌های قبلی منتقل شد', row.adopted ? 'بله' : 'هنوز نه'],
        ].map(([k, v]) => (
          <div
            key={k}
            className="flex items-start justify-between gap-4 border-b border-[var(--ln)] py-2.5 text-sm last:border-0"
          >
            <span className="shrink-0 text-[var(--mu)]">{k}</span>
            <span className="min-w-0 break-words text-left font-bold">{v ?? '—'}</span>
          </div>
        ))}
        {row.last_error && (
          <p className="mt-3 flex items-start gap-2 rounded-xl bg-[var(--bdb)] p-3 text-xs leading-6 text-[var(--bd)]">
            <AlertTriangle size={15} className="mt-0.5 shrink-0" />
            <span dir="auto" className="break-all">
              {row.last_error}
            </span>
          </p>
        )}
        {!row.profile_synced && (
          <p className="mt-3 flex items-start gap-2 rounded-xl bg-[var(--wnb)] p-3 text-xs leading-6 text-[var(--wn)]">
            <Clock size={15} className="mt-0.5 shrink-0" />
            آخرین ویرایش پروفایل هنوز روی پنل اعمال نشده؛ همگام‌سازی خودکار هر یک دقیقه دوباره تلاش می‌کند.
          </p>
        )}
      </section>

      <section className="card space-y-4 p-4">
        <div>
          <h4 className="text-[13px] font-extrabold">پروفایل و راه‌های تماس</h4>
          <p className="mt-1 text-xs leading-6 text-[var(--mu)]">
            اختیاری است و فقط شما آن را ویرایش می‌کنید. فقط موارد تغییرکرده به پنل فرستاده می‌شود.
          </p>
        </div>
        {FIELDS.map(([k, label, hint, adminOnly]) => (
          <Field key={k} label={adminOnly ? `${label} (فقط ادمین)` : label} hint={hint}>
            {k === 'note' ? (
              <textarea
                rows={2}
                className="inp"
                maxLength={500}
                value={form[k]}
                onChange={(e) => set(k, e.target.value)}
              />
            ) : (
              <input
                className="inp"
                dir={k === 'profile_title' ? 'auto' : 'ltr'}
                inputMode={k === 'telegram_id' ? 'numeric' : undefined}
                maxLength={k === 'profile_title' ? 128 : 512}
                value={form[k]}
                onChange={(e) => set(k, k === 'telegram_id' ? digits(e.target.value) : e.target.value)}
              />
            )}
          </Field>
        ))}
      </section>

      <section className="card space-y-3 p-4">
        <div>
          <h4 className="text-[13px] font-extrabold">اطلاعات ورود به داشبورد PasarGuard</h4>
          <p className="mt-1 text-xs leading-6 text-[var(--mu)]">
            هر نمایش رمز در ممیزی ثبت می‌شود و پس از ۶۰ ثانیه پنهان می‌گردد.
          </p>
        </div>
        {cred ? (
          <div className="space-y-2 rounded-xl bg-[var(--mb)] p-3 text-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[var(--mu)]">نام کاربری</span>
              <span className="inline-flex items-center gap-1.5">
                {ltr(cred.username)}
                <CopyButton text={cred.username} label="کپی نام کاربری" />
              </span>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-[var(--mu)]">رمز</span>
              <span className="inline-flex items-center gap-1.5">
                <code
                  dir="ltr"
                  data-testid="admin-password"
                  className="latin rounded bg-[var(--sf)] px-2 py-1 text-xs font-bold"
                >
                  {cred.password}
                </code>
                <CopyButton text={cred.password} label="کپی رمز" />
              </span>
            </div>
            {cred.panel_url && (
              <a
                dir="ltr"
                className="latin inline-flex items-center gap-1.5 text-xs text-[var(--in)] underline"
                href={cred.panel_url}
                target="_blank"
                rel="noopener noreferrer"
              >
                <ExternalLink size={13} />
                {cred.panel_url}
              </a>
            )}
          </div>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <button className="btn btn-g !py-2 !text-sm" disabled={busy} onClick={reveal}>
            <KeyRound size={15} />
            نمایش رمز
          </button>
          <button className="btn btn-g btn-d !py-2 !text-sm" disabled={busy || row.status !== 'active'} onClick={reset}>
            <RefreshCw size={15} />
            ساخت رمز جدید
          </button>
        </div>
      </section>

      {row.store_id && row.panel_id && row.status === 'active' && (
        <SubBrandingCard
          storeId={row.store_id}
          panelId={row.panel_id}
          panelName={row.panel_name}
          call={call}
          toast={toast}
        />
      )}
    </Drawer>
  );
}

function RequestDrawer({ req, call, toast, onClose, onDone }) {
  const { busy, error, setError, run } = useCall(call, toast);
  const pending = req.status === 'pending';
  const keys = FIELDS.map(([k]) => k).filter((k) => k in (req.changes || {}));
  const [on, setOn] = useState(() => Object.fromEntries(keys.map((k) => [k, true])));
  const asked = (k) => (req.changes[k] == null ? '' : String(req.changes[k]));
  const [vals, setVals] = useState(() => Object.fromEntries(keys.map((k) => [k, asked(k)])));
  const [note, setNote] = useState('');
  const edited = keys.some((k) => on[k] && vals[k] !== asked(k));

  const apply = async () => {
    const picked = keys.filter((k) => on[k]);
    if (!picked.length) return setError('حداقل یک مورد را برای اعمال انتخاب کنید.');
    if (picked.includes('telegram_id') && !vals.telegram_id.trim())
      return setError('آیدی تلگرام نمی‌تواند خالی باشد (پاک‌کردن پشتیبانی نمی‌شود).');
    if (
      !(await confirmDialog(
        `${num(picked.length)} مورد روی ادمین پنل «${req.store_name}» اعمال می‌شود${edited ? ' (با ویرایش شما)' : ''}.`,
        {
          title: 'اعمال تغییرات',
          ok: 'اعمال',
        },
      ))
    )
      return;
    const changes = Object.fromEntries(picked.map((k) => [k, k === 'telegram_id' ? Number(vals[k]) : vals[k].trim()]));
    const d = await run(
      `/api/v1/admin/panel-admin-requests/${req.id}/apply`,
      'POST',
      { changes, note: note.trim() || null },
      'تغییرات اعمال شد',
    );
    if (d) onDone();
  };
  const reject = async () => {
    if (
      !(await confirmDialog('درخواست رد می‌شود و توضیح شما برای نماینده ارسال می‌گردد.', {
        title: 'رد درخواست',
        danger: true,
        ok: 'رد درخواست',
      }))
    )
      return;
    const d = await run(
      `/api/v1/admin/panel-admin-requests/${req.id}/reject`,
      'POST',
      { note: note.trim() },
      'درخواست رد شد',
    );
    if (d) onDone();
  };

  return (
    <Drawer
      title={req.store_name || 'درخواست تغییر'}
      subtitle={`درخواست تغییر پروفایل ادمین پنل · ${dt(req.created_at)}`}
      icon={
        <span className="tile h-10 w-10 bg-[var(--inb)] text-[var(--in)]">
          <Inbox size={19} />
        </span>
      }
      dirty={pending && (edited || note.trim().length > 0)}
      busy={busy}
      error={error}
      onClose={onClose}
      footer={
        pending ? (
          <>
            <button className="btn !py-2 !text-sm" disabled={busy} onClick={apply}>
              <CheckCircle2 size={15} />
              اعمال تغییرات
            </button>
            <button
              className="btn btn-g btn-d !py-2 !text-sm"
              disabled={busy || note.trim().length < 3}
              title={note.trim().length < 3 ? 'برای رد، توضیح بنویسید' : undefined}
              onClick={reject}
            >
              <XCircle size={15} />
              رد درخواست
            </button>
          </>
        ) : null
      }
    >
      {req.message && (
        <p className="whitespace-pre-line rounded-xl bg-[var(--mb)] p-3 text-xs leading-6">{req.message}</p>
      )}
      <section className="card p-4">
        <h4 className="mb-2 text-[13px] font-extrabold">
          {pending ? 'تغییرات درخواستی (قابل ویرایش)' : 'تغییرات درخواستی'}
        </h4>
        <div className="space-y-3">
          {keys.map((k) => (
            <div key={k} className="rounded-xl border border-[var(--ln)] p-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="text-xs font-extrabold">{LABEL[k]}</span>
                {pending && (
                  <label className="flex items-center gap-1.5 text-xs text-[var(--mu)]">
                    <input
                      type="checkbox"
                      checked={on[k]}
                      onChange={(e) => setOn((o) => ({ ...o, [k]: e.target.checked }))}
                    />
                    اعمال شود
                  </label>
                )}
              </div>
              <div className="mb-2 text-[11px] text-[var(--mu)]">فعلی: {ltr(req.current_profile?.[k])}</div>
              {pending ? (
                <input
                  className="inp"
                  dir="ltr"
                  aria-label={`مقدار جدید ${LABEL[k]}`}
                  disabled={!on[k]}
                  inputMode={k === 'telegram_id' ? 'numeric' : undefined}
                  value={vals[k]}
                  onChange={(e) =>
                    setVals((v) => ({ ...v, [k]: k === 'telegram_id' ? digits(e.target.value) : e.target.value }))
                  }
                />
              ) : (
                <div className="text-sm font-bold">{ltr(req.changes[k])}</div>
              )}
            </div>
          ))}
        </div>
      </section>
      {pending ? (
        <section className="card p-4">
          <Field
            label="توضیح برای نماینده"
            hint="برای رد الزامی است؛ برای اعمال اختیاری و همراه اعلان به نماینده ارسال می‌شود."
          >
            <textarea rows={3} className="inp" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
        </section>
      ) : (
        <section className="card p-4">
          <h4 className="mb-1 text-[13px] font-extrabold">نتیجه</h4>
          {[
            ['وضعیت', <Badge key="s" s={req.status} />],
            ['زمان بررسی', dt(req.reviewed_at)],
            ['توضیح', req.review_note],
          ].map(([k, v]) => (
            <div
              key={k}
              className="flex items-start justify-between gap-4 border-b border-[var(--ln)] py-2.5 text-sm last:border-0"
            >
              <span className="shrink-0 text-[var(--mu)]">{k}</span>
              <span className="min-w-0 break-words text-left font-bold">{v ?? '—'}</span>
            </div>
          ))}
        </section>
      )}
    </Drawer>
  );
}

export default function PanelAdminsView({ api, toast }) {
  const call = (p, o = {}) => authFetch(api.base, p, o);
  const admins = useRows(call, '/api/v1/admin/panel-admins');
  const requests = useRows(call, '/api/v1/admin/panel-admin-requests?status='); // empty status = every request
  const [tab, setTab] = useState('admins');
  const [filter, setFilter] = useState('all');
  const [reqFilter, setReqFilter] = useState('pending');
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(null);
  const [openReq, setOpenReq] = useState(null);
  const [syncing, setSyncing] = useState(false);

  const rows = useMemo(() => admins.rows || [], [admins.rows]);
  const reqs = useMemo(() => requests.rows || [], [requests.rows]);
  const match = (r, f) => f === 'all' || (f === 'unsynced' ? !r.profile_synced : r.status === f);
  const count = (f) => rows.filter((r) => match(r, f)).length;
  const reqCount = (f) => (f === 'all' ? reqs.length : reqs.filter((r) => r.status === f).length);
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
            <h3 className="font-extrabold">ادمین‌های پنل</h3>
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
