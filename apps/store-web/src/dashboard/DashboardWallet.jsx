import { useEffect, useState } from 'react';
import { fa, fd } from '../ui.jsx';
import { J, card, btn, inp } from './DashboardAccounts.jsx';

export function Wallet({ coreFetch, storeId, wallet, reload, notify }) {
  const [tx, setTx] = useState([]);
  const [amount, setAmount] = useState('');
  const [pay, setPay] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = () =>
    coreFetch(`/api/v1/stores/${storeId}/wallet/transactions`)
      .then((r) => r.json())
      .then((d) => setTx(Array.isArray(d) ? d : d.items || []))
      .catch(() => {});
  useEffect(() => {
    load();
  // eslint-disable-next-line react-hooks/exhaustive-deps -- T-W08: reviewed, dependency list intentionally limited (adding the flagged value risks refetch loops); verify in a browser before changing
  }, [storeId]);
  async function topup() {
    setBusy(true);
    try {
      const r = await coreFetch(`/api/v1/stores/${storeId}/wallet/topups`, {
        method: 'POST',
        headers: { ...J, 'Idempotency-Key': `topup-${crypto.randomUUID()}` },
        body: JSON.stringify({ amount: Number(amount), provider: 'manual_card' }),
      });
      if (!r.ok) throw 0;
      const p = await r.json();
      setPay(p);
      if (p.instructions?.redirect_url) window.location.href = p.instructions.redirect_url;
    } catch (e) {
      notify(e?.message || 'ایجاد درخواست شارژ ناموفق بود');
    } finally {
      setBusy(false);
    }
  }
  // Core reads the time, amount, card tail and reference from the image by itself (OCR / vision); the customer only picks the
  // photo. If Core could not read the time, a one-field fallback appears: the bank SMS stays the proof either way.
  const [rc, setRc] = useState({ file: null, paid_at: '' });
  const [read, setRead] = useState(null);
  const [sending, setSending] = useState(false);
  const resetReceipt = () => {
    setPay(null);
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
        resetReceipt();
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
              <button disabled={busy || !Number(amount)} onClick={topup} className={`${btn} mt-3 w-full`}>
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
                  onChange={(e) => setRc({ ...rc, file: e.target.files[0] || null })}
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
            {tx.map((t) => (
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
