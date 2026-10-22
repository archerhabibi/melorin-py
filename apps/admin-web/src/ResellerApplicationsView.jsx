// Reseller applications desk: review queue → drawer with everything the admin needs → approve (creates the store) or reject (reason is shown to the applicant).
import { useMemo, useState } from 'react';
import {
  AlertTriangle,
  BadgeCheck,
  Bot,
  CheckCircle2,
  Clock,
  Globe,
  RefreshCw,
  ShieldQuestion,
  Store,
  UserPlus,
  XCircle,
} from 'lucide-react';
import { authFetch } from './api.js';
import { Badge, confirmDialog, dt } from './ui.jsx';
import {
  Drawer,
  Empty,
  ErrorBar,
  Field,
  KpiBar,
  NumInput,
  Pills,
  SearchBox,
  Stat,
  errText,
  num,
  useRows,
} from './kit.jsx';

const STATUS_PILLS = [
  ['pending', 'در انتظار'],
  ['awaiting_details', 'منتظر دامنه و توکن'],
  ['approved', 'تأیید‌شده'],
  ['rejected', 'رد‌شده'],
  ['cancelled', 'لغو‌شده'],
  ['all', 'همه'],
];

function BotCell({ a }) {
  if (!a.bot_username && !a.has_bot_token) return <span className="text-[var(--mu)]">—</span>;
  return (
    <span className="inline-flex items-center gap-1.5">
      <Bot size={14} className="text-[var(--mu)]" />
      <span dir="ltr" className="latin text-xs font-bold">
        {a.bot_username ? `@${a.bot_username}` : 'نامشخص'}
      </span>
      {a.bot_verified ? (
        <BadgeCheck size={14} className="text-[var(--ok)]" aria-label="تأیید‌شده توسط تلگرام" />
      ) : (
        <ShieldQuestion size={14} className="text-[var(--wn)]" aria-label="هنوز تأیید نشده" />
      )}
    </span>
  );
}

function ReviewDrawer({ a, call, toast, onClose, onDone }) {
  const pending = a.status === 'pending';
  const awaiting = a.status === 'awaiting_details'; // approved as a request; the applicant still has to send domain + bot token
  const [debt, setDebt] = useState('0');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [bot, setBot] = useState(a);
  const twoStep = pending && !(a.domain && a.has_bot_token); // filed from Telegram: details are collected after approval

  const run = async (path, body, okMsg) => {
    setBusy(true);
    setError('');
    try {
      const r = await call(path, { method: 'POST', body: JSON.stringify(body || {}) });
      if (!r.ok) {
        setError(await errText(r, 'عملیات ناموفق بود'));
        return null;
      }
      toast(okMsg);
      return await r.json();
    } catch {
      setError('ارتباط با سرور برقرار نشد');
      return null;
    } finally {
      setBusy(false);
    }
  };
  const approve = async () => {
    const who = a.user_name || a.user_email || 'متقاضی';
    const warn = twoStep || bot.bot_verified ? '' : '\n\n⚠ ربات هنوز توسط تلگرام تأیید نشده است.';
    const msg = twoStep
      ? `درخواست «${a.store_name}» تأیید می‌شود. ${who} در ربات تلگرام دامنه و توکن ربات را می‌فرستد و فروشگاه با همان اطلاعات ساخته می‌شود. سقف بدهی: ${num(debt)}.`
      : `فروشگاه «${a.store_name}» روی دامنهٔ ${a.domain} ساخته می‌شود و ${who} مالک آن خواهد بود. سقف بدهی: ${num(debt)}.${warn}`;
    if (
      !(await confirmDialog(msg, { title: 'تأیید نمایندگی', ok: twoStep ? 'تأیید درخواست' : 'تأیید و ساخت فروشگاه' }))
    )
      return;
    const d = await run(
      `/api/v1/admin/reseller-applications/${a.id}/review`,
      { approve: true, debt_limit: Number(debt || 0), reason: reason.trim() || null },
      twoStep ? 'درخواست تأیید شد؛ منتظر دامنه و توکن از متقاضی' : 'نمایندگی تأیید شد و فروشگاه ساخته شد',
    );
    if (d) onDone();
  };
  const reject = async () => {
    if (
      !(await confirmDialog('درخواست رد می‌شود و دلیل شما به متقاضی نمایش داده می‌شود.', {
        title: 'رد درخواست',
        danger: true,
        ok: 'رد درخواست',
      }))
    )
      return;
    const d = await run(
      `/api/v1/admin/reseller-applications/${a.id}/review`,
      { approve: false, reason: reason.trim() },
      'درخواست رد شد',
    );
    if (d) onDone();
  };
  const recheck = async () => {
    const d = await run(`/api/v1/admin/reseller-applications/${a.id}/verify-bot`, null, 'ربات توسط تلگرام تأیید شد');
    if (d) setBot(d);
  };

  const row = (k, v) => (
    <div className="flex items-start justify-between gap-4 border-b border-[var(--ln)] py-2.5 text-sm last:border-0">
      <span className="shrink-0 text-[var(--mu)]">{k}</span>
      <span className="min-w-0 break-words text-left font-bold">{v ?? '—'}</span>
    </div>
  );

  return (
    <Drawer
      title={a.store_name}
      subtitle={`درخواست نمایندگی · ${dt(a.created_at)}`}
      icon={
        <span className="tile h-10 w-10 bg-[var(--inb)] text-[var(--in)]">
          <UserPlus size={19} />
        </span>
      }
      busy={busy}
      error={error}
      onClose={onClose}
      footer={
        pending || awaiting ? (
          <>
            {pending && (
              <button className="btn !py-2 !text-sm" disabled={busy} onClick={approve}>
                <CheckCircle2 size={15} />
                {twoStep ? 'تأیید درخواست' : 'تأیید و ساخت فروشگاه'}
              </button>
            )}
            <button
              className="btn btn-g btn-d !py-2 !text-sm"
              disabled={busy || reason.trim().length < 3}
              onClick={reject}
              title={reason.trim().length < 3 ? 'برای رد، دلیل بنویسید' : undefined}
            >
              <XCircle size={15} />
              {awaiting ? 'لغو تأیید و رد' : 'رد درخواست'}
            </button>
          </>
        ) : null
      }
    >
      <section className="card p-4">
        <h4 className="mb-1 text-[13px] font-extrabold">متقاضی</h4>
        {row('نام', a.user_name)}
        {row(
          'ایمیل',
          <span dir="ltr" className="latin">
            {a.user_email}
          </span>,
        )}
        {row('فروشگاه مقصد', a.target_store_name)}
        {a.message && (
          <p className="mt-3 whitespace-pre-line rounded-xl bg-[var(--mb)] p-3 text-xs leading-6">{a.message}</p>
        )}
      </section>
      <section className="card p-4">
        <h4 className="mb-1 text-[13px] font-extrabold">فروشگاه نمایندگی</h4>
        {row('نام فروشگاه', a.store_name)}
        {row(
          'دامنه',
          a.domain ? (
            <a
              dir="ltr"
              className="latin text-[var(--in)] underline"
              href={`https://${a.domain}`}
              target="_blank"
              rel="noopener noreferrer"
            >
              {a.domain}
            </a>
          ) : (
            <span className="text-[var(--mu)]">هنوز ارسال نشده</span>
          ),
        )}
        {row(
          'ربات تلگرام',
          <span className="inline-flex flex-col items-end gap-1">
            <BotCell a={bot} />
            {pending && !twoStep && !bot.bot_verified && (
              <button className="btn btn-g !py-1 !text-xs" disabled={busy} onClick={recheck}>
                <RefreshCw size={12} />
                بررسی دوباره با تلگرام
              </button>
            )}
          </span>,
        )}
        {row(
          'توکن ربات',
          a.has_bot_token
            ? 'ذخیره‌شده (رمزنگاری‌شده و غیرقابل نمایش)'
            : twoStep || awaiting
              ? 'هنوز ارسال نشده'
              : 'حذف‌شده',
        )}
      </section>
      {twoStep && (
        <p className="flex items-start gap-2 rounded-xl bg-[var(--inb)] p-3 text-xs leading-6 text-[var(--in)]">
          <AlertTriangle size={15} className="mt-0.5 shrink-0" />
          این درخواست بدون دامنه و ربات ثبت شده (از ربات تلگرام). با تأیید، متقاضی در تلگرام دامنه و توکن را می‌فرستد و
          فروشگاه همان لحظه ساخته می‌شود.
        </p>
      )}
      {awaiting && (
        <p className="flex items-start gap-2 rounded-xl bg-[var(--inb)] p-3 text-xs leading-6 text-[var(--in)]">
          <Clock size={15} className="mt-0.5 shrink-0" />
          تأیید شده؛ منتظر دامنه و توکن ربات از متقاضی هستیم. سقف بدهی تأییدشده: {num(a.approved_debt_limit ?? 0)}. برای
          منصرف‌شدن، دلیل را بنویسید و «لغو تأیید و رد» را بزنید.
        </p>
      )}
      {pending && !twoStep && !bot.bot_verified && (
        <p className="flex items-start gap-2 rounded-xl bg-[var(--wnb)] p-3 text-xs leading-6 text-[var(--wn)]">
          <AlertTriangle size={15} className="mt-0.5 shrink-0" />
          ربات هنوز توسط تلگرام تأیید نشده؛ قبل از تأیید «بررسی دوباره» را بزنید.
        </p>
      )}
      {pending || awaiting ? (
        <section className="card space-y-4 p-4">
          <h4 className="text-[13px] font-extrabold">تصمیم</h4>
          {pending && (
            <Field
              label="سقف بدهی نماینده"
              hint="تا چه مبلغی می‌تواند بدون شارژ کیف پول اصلی خود بفروشد؛ پیش‌فرض صفر است."
            >
              <NumInput value={debt} onChange={setDebt} suffix="IRT" />
            </Field>
          )}
          <Field label="دلیل / توضیح" hint="برای رد الزامی است و به متقاضی نمایش داده می‌شود.">
            <textarea
              rows={3}
              className="inp"
              maxLength={500}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </Field>
        </section>
      ) : (
        <section className="card p-4">
          <h4 className="mb-1 text-[13px] font-extrabold">نتیجه</h4>
          {row('وضعیت', <Badge s={a.status} />)}
          {row('زمان بررسی', dt(a.reviewed_at))}
          {row('توضیح', a.review_reason)}
          {a.store_id &&
            row(
              'شناسهٔ فروشگاه',
              <span dir="ltr" className="latin text-xs">
                {a.store_id}
              </span>,
            )}
        </section>
      )}
    </Drawer>
  );
}

export default function ResellerApplicationsView({ api, toast }) {
  const call = (p, o = {}) => authFetch(api.base, p, o);
  const { rows, failed, load } = useRows(call, '/api/v1/admin/reseller-applications');
  const [filter, setFilter] = useState('pending');
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(null);

  const all = rows || [];
  const count = (s) => (s === 'all' ? all.length : all.filter((x) => x.status === s).length);
  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    return all.filter(
      (x) =>
        (filter === 'all' || x.status === filter) &&
        (!t ||
          [x.store_name, x.domain, x.user_email, x.user_name, x.bot_username].some((v) =>
            (v || '').toLowerCase().includes(t),
          )),
    );
  }, [all, filter, q]);
  const unverified = all.filter((x) => x.status === 'pending' && !x.bot_verified).length;

  return (
    <div className="space-y-5">
      <KpiBar cols={4}>
        <Stat
          label="در انتظار بررسی"
          value={count('pending')}
          tone="wn"
          Icon={Clock}
          active={filter === 'pending'}
          onClick={() => setFilter('pending')}
        />
        <Stat
          label="تأیید‌شده"
          value={count('approved')}
          tone="ok"
          Icon={CheckCircle2}
          active={filter === 'approved'}
          onClick={() => setFilter('approved')}
        />
        <Stat
          label="رد‌شده"
          value={count('rejected')}
          tone="bd"
          Icon={XCircle}
          active={filter === 'rejected'}
          onClick={() => setFilter('rejected')}
        />
        <Stat label="ربات تأییدنشده" value={unverified} tone="in" Icon={ShieldQuestion} sub="در صف انتظار" />
      </KpiBar>
      <section className="card rise overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--ln)] px-5 py-4">
          <div>
            <h3 className="font-extrabold">درخواست‌های نمایندگی</h3>
            <p className="mt-1 text-xs text-[var(--mu)]">بررسی، تأیید و ساخت فروشگاه نماینده</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Pills
              label="فیلتر وضعیت"
              value={filter}
              onChange={setFilter}
              options={STATUS_PILLS.map(([k, l]) => [k, l, count(k), { warn: k === 'pending' }])}
            />
            <SearchBox value={q} onChange={setQ} placeholder="نام، دامنه، ایمیل، ربات…" label="جستجو در درخواست‌ها" />
          </div>
        </div>
        {failed && (
          <div className="p-4">
            <ErrorBar onRetry={load}>دریافت درخواست‌ها ناموفق بود</ErrorBar>
          </div>
        )}
        <div className="max-h-[70vh] overflow-auto">
          <table className="tbl min-w-[860px]">
            <thead>
              <tr>
                <th>متقاضی</th>
                <th>فروشگاه نمایندگی</th>
                <th>دامنه</th>
                <th>ربات</th>
                <th>فروشگاه مقصد</th>
                <th>ثبت</th>
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
                shown.map((a) => (
                  <tr key={a.id} className="cursor-pointer" onClick={() => setOpen(a)}>
                    <td>
                      <div className="font-bold">{a.user_name || '—'}</div>
                      <div dir="ltr" className="latin text-right text-xs text-[var(--mu)]">
                        {a.user_email}
                      </div>
                    </td>
                    <td className="font-bold">
                      <span className="inline-flex items-center gap-1.5">
                        <Store size={14} className="text-[var(--mu)]" />
                        {a.store_name}
                      </span>
                    </td>
                    <td>
                      {a.domain ? (
                        <span dir="ltr" className="latin inline-flex items-center gap-1.5 text-xs">
                          <Globe size={13} className="text-[var(--mu)]" />
                          {a.domain}
                        </span>
                      ) : (
                        <span className="text-[var(--mu)]">—</span>
                      )}
                    </td>
                    <td>
                      <BotCell a={a} />
                    </td>
                    <td className="text-xs text-[var(--mu)]">{a.target_store_name || '—'}</td>
                    <td className="text-xs text-[var(--mu)]">{dt(a.created_at)}</td>
                    <td>
                      <Badge s={a.status} />
                    </td>
                    <td>
                      <button
                        className="btn btn-g !py-1.5 !text-xs"
                        onClick={(e) => {
                          e.stopPropagation();
                          setOpen(a);
                        }}
                      >
                        {a.status === 'pending' ? 'بررسی' : 'جزئیات'}
                      </button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={8}>
                    <Empty
                      Icon={UserPlus}
                      title="درخواستی در این فیلتر نیست"
                      text={
                        filter === 'pending' ? 'درخواست جدیدی منتظر بررسی نیست.' : 'فیلتر یا عبارت جستجو را تغییر دهید.'
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
        <ReviewDrawer
          key={open.id}
          a={open}
          call={call}
          toast={toast}
          onClose={() => setOpen(null)}
          onDone={() => {
            setOpen(null);
            load();
            api.refresh?.();
          }}
        />
      )}
    </div>
  );
}
