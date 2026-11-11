// Dialog bodies shown inside <Modal> by App (split out of App.jsx, T-R11). State stays in App; these only render.
import { CreditCard, Loader2, Lock, Mail } from 'lucide-react';
import { fa } from './ui.tsx';
import { GoogleSignInButton } from './GoogleSignIn.tsx';
import TelegramLoginButtons from './TelegramLoginButtons.tsx';
import { focusOnMount } from './useDialog.ts';
import type { Json } from './types';

export function LoginDialog({
  showTg,
  base,
  storeId,
  tgBot,
  tgOidc,
  setModal,
  email,
  setEmail,
  validEmail,
  busy,
  run,
  requestCode,
  handleGoogleCredential,
}: {
  showTg?: Json;
  base?: Json;
  storeId?: Json;
  tgBot?: Json;
  tgOidc?: Json;
  setModal?: Json;
  email?: Json;
  setEmail?: Json;
  validEmail?: Json;
  busy?: Json;
  run?: Json;
  requestCode?: Json;
  handleGoogleCredential?: Json;
}) {
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        validEmail && run(requestCode, 'ارسال کد ناموفق بود');
      }}
    >
      <p className="mt-2 text-sm leading-7 text-muted">
        رمز عبور لازم نیست؛ با تأیید در تلگرام یا کدی که به ایمیلت می‌آید وارد شو. اگر حساب نداشته باشی، خودکار ساخته
        می‌شود.
      </p>
      {showTg && (
        <>
          <TelegramLoginButtons
            base={base}
            storeId={storeId}
            bot={tgBot}
            direct={tgOidc}
            onBot={() => setModal('telegram')}
          />
          <div className="mt-4 flex items-center gap-3">
            <span className="h-px flex-1 bg-line" />
            <span className="text-xs text-muted">یا با ایمیل</span>
            <span className="h-px flex-1 bg-line" />
          </div>
        </>
      )}
      <label className={`${showTg ? 'mt-4' : 'mt-6'} block text-xs font-bold`}>
        ایمیل
        <div className="relative mt-1.5">
          <Mail size={17} className="pointer-events-none absolute right-3.5 top-1/2 -translate-y-1/2 text-muted" />
          <input
            type="email"
            dir="ltr"
            autoComplete="email"
            inputMode="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="input !pr-10 text-left"
            placeholder="email@example.com"
          />
        </div>
      </label>
      <button type="submit" disabled={!validEmail || busy} className="btn-primary mt-5 w-full">
        {busy ? <Loader2 size={18} className="animate-spin" /> : <Mail size={18} />}ارسال کد ورود
      </button>
      <p className="mt-4 flex items-center justify-center gap-1.5 text-xs text-muted">
        <Lock size={13} />
        ایمیل تو نزد ما محفوظ می‌ماند.
      </p>
      <div className="my-4 flex items-center gap-3">
        <span className="h-px flex-1 bg-line" />
        <span className="text-xs text-muted">یا</span>
        <span className="h-px flex-1 bg-line" />
      </div>
      <GoogleSignInButton onCredential={handleGoogleCredential} text="continue_with" disabled={busy} />
    </form>
  );
}

export function GoogleLinkDialog({ linkGoogleNow, setModal }: { linkGoogleNow?: Json; setModal?: Json }) {
  return (
    <div>
      <p className="mt-2 text-sm leading-7 text-muted">
        با ورود شما از تلگرام وارد شدید. برای اینکه با گوگل هم به همین حساب برسید، یک‌بار حساب گوگل‌تان را تأیید کنید.
      </p>
      <GoogleSignInButton onCredential={linkGoogleNow} text="continue_with" className="mt-4" />
      <button onClick={() => setModal('')} className="btn-soft mt-4 w-full">
        بعداً
      </button>
    </div>
  );
}

export function CodeDialog({
  email,
  loginCode,
  setLoginCode,
  busy,
  run,
  verifyCode,
  setModal,
}: {
  email?: Json;
  loginCode?: Json;
  setLoginCode?: Json;
  busy?: Json;
  run?: Json;
  verifyCode?: Json;
  setModal?: Json;
}) {
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        loginCode && run(verifyCode, 'کد نامعتبر است');
      }}
    >
      <p className="mt-2 text-sm leading-7 text-muted">
        کد ارسال‌شده به <b className="latin text-ink">{email}</b> را وارد کن.
      </p>
      <input
        ref={focusOnMount}
        dir="ltr"
        inputMode="numeric"
        autoComplete="one-time-code"
        value={loginCode}
        onChange={(e) => setLoginCode(e.target.value.trim())}
        className="input mt-6 !py-4 text-center text-2xl font-black tracking-[.5em]"
        placeholder="••••••"
        aria-label="کد ورود"
      />
      <button type="submit" disabled={!loginCode || busy} className="btn-primary mt-5 w-full">
        {busy && <Loader2 size={18} className="animate-spin" />}تأیید و ورود
      </button>
      <button
        type="button"
        onClick={() => setModal('login')}
        className="mt-3 w-full text-center text-xs font-bold text-muted hover:text-ink"
      >
        تغییر ایمیل یا ارسال دوباره
      </button>
    </form>
  );
}

export function CheckoutDialog({
  active,
  bundle,
  panelLabel,
  customName,
  accountName,
  selectedQuote,
  busy,
  run,
  buySelected,
  setModal,
}: {
  active?: Json;
  bundle?: Json;
  panelLabel?: Json;
  customName?: Json;
  accountName?: Json;
  selectedQuote?: Json;
  busy?: Json;
  run?: Json;
  buySelected?: Json;
  setModal?: Json;
}) {
  return (
    <>
      <p className="mt-2 text-sm text-muted">خلاصه سفارش را بررسی و از کیف پول پرداخت کن.</p>
      <dl className="mt-6 divide-y divide-line rounded-2xl bg-surface2 px-4 text-sm">
        <div className="flex justify-between py-3.5">
          <dt className="text-muted">سرویس</dt>
          <dd className="font-bold">{active}</dd>
        </div>
        {bundle && (
          <div className="flex justify-between py-3.5">
            <dt className="text-muted">بسته</dt>
            <dd className="font-bold">
              {bundle.name}
              {panelLabel ? ` · ${panelLabel}` : ''}
            </dd>
          </div>
        )}
        {customName && (
          <div className="flex justify-between py-3.5">
            <dt className="text-muted">نام کاربری</dt>
            <dd className="latin font-bold">{accountName.trim() || 'خودکار'}</dd>
          </div>
        )}
        <div className="flex justify-between py-3.5">
          <dt className="text-muted">مبلغ نهایی</dt>
          <dd className="text-lg font-black">
            {new Intl.NumberFormat('fa-IR').format(selectedQuote?.total || 0)}{' '}
            <span className="text-xs font-semibold">{selectedQuote?.currency}</span>
          </dd>
        </div>
        <div className="flex justify-between py-3.5">
          <dt className="text-muted">موجودی کیف پول</dt>
          <dd className={`font-bold ${selectedQuote?.sufficient_funds ? 'text-mint' : 'text-danger'}`}>
            {new Intl.NumberFormat('fa-IR').format(selectedQuote?.wallet_balance || 0)}
          </dd>
        </div>
      </dl>
      {selectedQuote && !selectedQuote.sufficient_funds && (
        <p className="mt-3 rounded-xl bg-danger-soft px-4 py-3 text-xs font-bold leading-6 text-danger">
          موجودی کافی نیست. ابتدا از بخش «کیف پول» حساب را شارژ کن.
        </p>
      )}
      <button
        disabled={!selectedQuote?.sufficient_funds || busy}
        onClick={() => run(buySelected, 'ثبت سفارش ناموفق بود')}
        className="btn-primary mt-5 w-full"
      >
        {busy ? <Loader2 size={18} className="animate-spin" /> : <CreditCard size={18} />}پرداخت از کیف پول و ثبت سفارش
      </button>
      {selectedQuote && !selectedQuote.sufficient_funds && (
        <button
          onClick={() => {
            setModal('');
            window.location.hash = '#/dashboard';
          }}
          className="btn-soft mt-3 w-full"
        >
          رفتن به کیف پول
        </button>
      )}
    </>
  );
}

export function AccountDialog({ wallet, orders }: { wallet?: Json; orders?: Json }) {
  return (
    <>
      <div className="mt-5 rounded-2xl bg-mint-soft p-4">
        موجودی: {new Intl.NumberFormat('fa-IR').format(wallet?.balance || 0)} {wallet?.currency}
      </div>
      <p className="mt-4 text-sm">سفارش‌ها: {fa(orders.length)}</p>
    </>
  );
}
