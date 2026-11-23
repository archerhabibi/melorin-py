import { useEffect, useRef, useState } from 'react';
import { fa, fd } from '../ui.tsx';
import { updateStoredAttempt } from '../attemptLock.ts';
import { J, card, btn, inp } from './DashboardAccounts.tsx';
import type { Json } from '../types';

export function Wallet({
  coreFetch,
  storeId,
  accountId,
  wallet,
  reload,
  notify,
}: {
  coreFetch?: Json;
  storeId?: Json;
  accountId?: string;
  wallet?: Json;
  reload?: Json;
  notify?: Json;
}) {
  const [tx, setTx] = useState<Json>([]);
  const [amount, setAmount] = useState('');
  const [pay, setPay] = useState<Json>(null);
  const [paymentAttemptKey, setPaymentAttemptKey] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submitting = useRef(false);
  const topupStorageKey =
    typeof storeId === 'string' && storeId.trim() && typeof accountId === 'string' && accountId.trim()
      ? `melorin:wallet-topup:${encodeURIComponent(storeId)}:${encodeURIComponent(accountId)}`
      : null;
  // state: 'unknown' = the outcome of the last request is not known (network error / 5xx / unknown-outcome code), so the same
  // key must be reused; 'active' = a payment exists and was received, so a different amount may start a fresh request.
  type TopupAttempt = { amount?: string; idempotencyKey?: string; state?: 'unknown' | 'active' };
  const updateAttempt = async (expectedKey: string, next: TopupAttempt | null) => {
    if (!topupStorageKey) return;
    try {
      await updateStoredAttempt(topupStorageKey, (raw) => {
        const saved: TopupAttempt | null = JSON.parse(raw || 'null');
        // A response or receipt from an older tab cannot replace a newer attempt.
        if (saved?.idempotencyKey !== expectedKey) return { result: undefined };
        return { value: next ? JSON.stringify(next) : null, result: undefined };
      });
    } catch {
      /* Keep the stored key when safe coordination is unavailable. */
    }
  };
  const load = () =>
    coreFetch(`/api/v1/stores/${storeId}/wallet/transactions`)
      .then((r: Json) => r.json())
      .then((d: Json) => setTx(Array.isArray(d) ? d : d.items || []))
      .catch(() => {});
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- T-W08: reviewed, dependency list intentionally limited (adding the flagged value risks refetch loops); verify in a browser before changing
  }, [storeId]);
  async function topup() {
    if (!topupStorageKey) {
      notify('برای ایجاد درخواست شارژ، اطلاعات حساب باید بارگذاری شود.');
      return;
    }
    if (submitting.current) return;
    submitting.current = true;
    setBusy(true);
    const requestedAmount = String(Number(amount));
    try {
      let idempotencyKey: string | null;
      try {
        idempotencyKey = await updateStoredAttempt(topupStorageKey, (raw) => {
          const saved: TopupAttempt | null = raw ? JSON.parse(raw) : null;
          if (
            raw &&
            (!saved ||
              typeof saved !== 'object' ||
              typeof saved.idempotencyKey !== 'string' ||
              !saved.idempotencyKey ||
              typeof saved.amount !== 'string' ||
              (saved.state && saved.state !== 'unknown' && saved.state !== 'active'))
          )
            throw new Error('invalid stored attempt');
          if (saved?.idempotencyKey && saved.amount !== requestedAmount && saved.state !== 'active')
            return { result: null };
          const key =
            saved?.idempotencyKey && saved.amount === requestedAmount
              ? saved.idempotencyKey
              : 'topup-' + crypto.randomUUID();
          // Persist before sending, in the same cross-tab transaction that chose the key.
          return {
            value: JSON.stringify({
              amount: requestedAmount,
              idempotencyKey: key,
              state: saved?.idempotencyKey === key && saved.state === 'active' ? 'active' : 'unknown',
            }),
            result: key,
          };
        });
      } catch {
        notify('ذخیره امن وضعیت درخواست در مرورگر ممکن نیست؛ برای جلوگیری از پرداخت تکراری، درخواست ارسال نشد.');
        return;
      }
      if (!idempotencyKey) {
        notify(
          'نتیجهٔ درخواست شارژ قبلی هنوز مشخص نیست. برای جلوگیری از پرداخت تکراری، همان مبلغ قبلی را دوباره ارسال کنید یا با پشتیبانی تماس بگیرید.',
        );
        return;
      }
      const r = await coreFetch('/api/v1/stores/' + encodeURIComponent(String(storeId)) + '/wallet/topups', {
        method: 'POST',
        headers: { ...J, 'Idempotency-Key': idempotencyKey },
        body: JSON.stringify({ amount: Number(requestedAmount), provider: 'manual_card' }),
      });
      if (!r.ok) {
        const error = await r.json().catch(() => ({}));
        // Another tab may have sent this same key successfully even when this response is a 4xx.
        notify(error?.error?.message || 'ایجاد درخواست شارژ ناموفق بود');
        return;
      }
      const p = await r.json().catch(() => null);
      if (!p || typeof p.id !== 'string' || !p.id || typeof p.status !== 'string' || !p.status) {
        notify('نتیجهٔ درخواست شارژ مشخص نیست؛ همان مبلغ را دوباره ارسال کنید.');
        return;
      }
      if (p.status === 'failed' || p.status === 'cancelled') await updateAttempt(idempotencyKey, null);
      else await updateAttempt(idempotencyKey, { amount: requestedAmount, idempotencyKey, state: 'active' });
      setPaymentAttemptKey(idempotencyKey);
      setPay(p);
      if (p.instructions?.redirect_url) window.location.href = p.instructions.redirect_url;
    } catch (e: Json) {
      notify(e?.message || 'ایجاد درخواست شارژ ناموفق بود');
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }
  // Core reads the time, amount, card tail and reference from the image by itself (OCR / vision); the customer only picks the
  // photo. If Core could not read the time, a one-field fallback appears: the bank SMS stays the proof either way.
  const [rc, setRc] = useState<Json>({ file: null, paid_at: '' });
  const [read, setRead] = useState<Json>(null);
  const [sending, setSending] = useState(false);
  const resetReceipt = async () => {
    if (paymentAttemptKey) await updateAttempt(paymentAttemptKey, null);
    setPay(null);
    setPaymentAttemptKey(null);
    setAmount('');
    setRc({ file: null, paid_at: '' });
    setRead(null);
  };
  async function receipt() {
    if (!rc.file || sending) return;
    setSending(true);
    try {
      const fd_ = new FormData();
      fd_.append('file', rc.file);
      if (rc.paid_at.trim()) fd_.append('paid_at', rc.paid_at.trim());
      const r = await coreFetch(`/api/v1/stores/${storeId}/payments/${pay.id}/receipt`, { method: 'POST', body: fd_ });
      if (!r.ok) {
        let msg = 'ارسال رسید ناموفق بود';
        try {
          msg = (await r.json())?.error?.message || msg;
        } catch {
          /* non-JSON error body */
        }
        notify(msg);
        return;
      }
      const done = await r.json().catch(() => ({}));
      if (done.status === 'succeeded') {
        notify('پرداخت با پیامک بانک تأیید شد و کیف پول شما شارژ شد ✅');
        await resetReceipt();
        reload();
        load();
      } else if (!done.receipt_read?.paid_at) {
        setRead({ unread: true });
        notify('زمان رسید خوانده نشد؛ لطفاً آن را وارد کنید.');
      } else {
        setRead({ unread: false, at: done.receipt_read.paid_at });
        notify('رسید خوانده شد؛ به محض رسیدن تأییدیه‌ی بانک، کیف پول خودکار شارژ می‌شود.');
        reload();
        load();
      }
    } finally {
      setSending(false);
    }
  }
  return (
    <div className="grid gap-5 md:grid-cols-[.8fr_1.2fr]">
      <div className="space-y-4">
        <div className="rounded-2xl bg-hero p-6 text-white">
          <div className="text-sm text-white/60">موجودی</div>
          <div className="mt-2 text-3xl font-extrabold">
            {fa(wallet?.balance)} <span className="text-sm font-normal">{wallet?.currency}</span>
          </div>
          <div className="mt-4 flex items-center justify-between gap-2 border-t border-white/15 pt-3 text-sm">
            <span className="text-white/60">آیدی عددی تلگرام</span>
            {wallet?.telegram_id ? (
              <button
                type="button"
                title="کپی"
                className="latin font-bold"
                onClick={() =>
                  navigator.clipboard?.writeText(String(wallet.telegram_id)).then(
                    () => notify('کپی شد'),
                    () => {},
                  )
                }
              >
                {wallet.telegram_id}
              </button>
            ) : (
              <span className="text-white/60">متصل نیست</span>
            )}
          </div>
        </div>
        <div className={card}>
          <h4 className="font-extrabold">شارژ کیف پول</h4>
          {!pay ? (
            <>
              <input
                className={`${inp} mt-3`}
                inputMode="numeric"
                placeholder="مبلغ"
                value={amount}
                onChange={(e) => setAmount(e.target.value.replace(/\D/g, ''))}
              />
              {!topupStorageKey && (
                <p role="status" className="mt-2 text-xs text-muted">
                  برای ایجاد درخواست شارژ، اطلاعات حساب باید بارگذاری شود.
                </p>
              )}
              <button
                disabled={busy || !Number(amount) || !topupStorageKey}
                onClick={topup}
                className={`${btn} mt-3 w-full`}
              >
                ایجاد درخواست
              </button>
            </>
          ) : (
            <>
              <div className="mt-3 rounded-xl bg-accent-soft p-3 text-sm leading-7">
                {pay.instructions?.card_number ? (
                  <>
                    کارت: <b className="latin">{pay.instructions.card_number}</b>
                    <br />
                    {pay.instructions.holder}
                  </>
                ) : (
                  'دستورالعمل پرداخت را دنبال کنید.'
                )}
                <br />
                مبلغ: {fa(pay.amount)} {pay.currency}
              </div>
              <label className="mt-3 block cursor-pointer rounded-xl border border-dashed border-line p-4 text-center text-sm font-bold">
                {rc.file ? rc.file.name : 'انتخاب تصویر رسید'}
                <input
                  type="file"
                  accept="image/*,.pdf"
                  className="hidden"
                  onChange={(e) => setRc({ ...rc, file: e.target.files?.[0] || null })}
                />
              </label>
              {read?.unread && (
                <label className="mt-3 block text-xs font-bold">
                  زمان درج‌شده روی رسید (خوانده نشد)
                  <input
                    dir="ltr"
                    className={`${inp} mt-1 latin`}
                    inputMode="numeric"
                    placeholder="1405/08/02 22:50"
                    value={rc.paid_at}
                    onChange={(e) => setRc({ ...rc, paid_at: e.target.value })}
                  />
                </label>
              )}
              {read && !read.unread && (
                <p className="mt-3 rounded-xl bg-accent-soft p-3 text-xs leading-6">
                  رسید ثبت شد و زمان آن خوانده شد ({fd(read.at)}). منتظر تأییدیه‌ی بانک هستیم؛ نیازی به کار دیگری نیست.
                </p>
              )}
              {!read || read.unread ? (
                <>
                  <p className="mt-2 text-xs leading-6 text-muted">
                    فقط تصویر رسید را بفرستید؛ زمان و مبلغ به‌صورت خودکار از روی آن خوانده می‌شود.
                  </p>
                  <button disabled={!rc.file || sending} onClick={receipt} className={`${btn} mt-3 w-full`}>
                    {sending ? 'در حال خواندن رسید…' : read?.unread ? 'ثبت زمان و بررسی دوباره' : 'ارسال رسید'}
                  </button>
                </>
              ) : (
                <button onClick={resetReceipt} className={`${btn} mt-3 w-full`}>
                  بستن
                </button>
              )}
            </>
          )}
        </div>
      </div>
      <div className={card}>
        <h4 className="font-extrabold">تراکنش‌ها</h4>
        {tx.length ? (
          <div className="mt-3 divide-y divide-line">
            {tx.map((t: Json) => (
              <div key={t.transaction_id} className="flex justify-between py-3 text-sm">
                <div>
                  <div className="font-bold">{t.kind}</div>
                  <div className="text-xs text-muted">
                    {t.memo || ''} · {fd(t.created_at)}
                  </div>
                </div>
                <b className={t.amount < 0 ? 'text-danger' : 'text-mint'} dir="ltr">
                  {fa(t.amount)}
                </b>
              </div>
            ))}
          </div>
        ) : (
          <p className="mt-3 text-sm text-muted">تراکنشی ثبت نشده.</p>
        )}
      </div>
    </div>
  );
}
