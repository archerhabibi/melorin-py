import { useState } from 'react';
import {
  AlertTriangle,
  BadgeCheck,
  Bot,
  CheckCircle2,
  Clock,
  RefreshCw,
  ShieldQuestion,
  UserPlus,
  XCircle,
} from 'lucide-react';
import { Badge, confirmDialog, dt } from '../../shared/ui.tsx';
import { Drawer, Field, NumInput, errText, num } from '../../shared/kit.tsx';
import type { CallFn, Json, Toast } from '../../shared/types.ts';

export function BotCell({ a }: { a?: Json }) {
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

export function ReviewDrawer({
  a,
  call,
  toast,
  onClose,
  onDone,
}: {
  a?: Json;
  call: CallFn;
  toast: Toast;
  onClose?: Json;
  onDone?: Json;
}) {
  const pending = a.status === 'pending';
  const awaiting = a.status === 'awaiting_details'; // approved as a request; the applicant still has to send domain + bot token
  const [debt, setDebt] = useState('0');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [bot, setBot] = useState(a);
  const twoStep = pending && !(a.domain && a.has_bot_token); // filed from Telegram: details are collected after approval

  const run = async (path: string, body: Json, okMsg: Json) => {
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

  const row = (k: Json, v: Json) => (
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
