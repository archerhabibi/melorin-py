// "My account" call-to-action band on the landing page (split out of App.jsx, T-R11).
import { ArrowLeft } from 'lucide-react';
import { fa } from './ui.tsx';
import type { Json } from './types';

export function AccountBanner({
  wallet,
  orders,
  goAccount,
  accessToken,
}: {
  wallet?: Json;
  orders?: Json;
  goAccount?: Json;
  accessToken?: Json;
}) {
  return (
    <section id="account" className="px-5 pb-24">
      <div className="relative mx-auto max-w-6xl overflow-hidden rounded-4xl bg-mint-soft px-7 py-12 md:px-14">
        <div className="absolute -left-20 -top-24 h-64 w-64 rounded-full bg-mint/10 blur-2xl" />
        <div className="relative flex flex-col justify-between gap-8 md:flex-row md:items-center">
          <div>
            <div className="text-sm font-extrabold text-mint">حساب من</div>
            <h2 className="mt-3 text-3xl font-black">سرویس، کیف پول، سفارش‌ها.</h2>
            <p className="mt-3 max-w-md leading-8 text-muted">
              {wallet
                ? `موجودی کیف پول: ${new Intl.NumberFormat('fa-IR').format(wallet.balance)} ${wallet.currency} · ${fa(orders.length)} سفارش`
                : 'همه‌چیز آماده است تا از همان جایی که بودی ادامه بدهی.'}
            </p>
          </div>
          <button onClick={goAccount} className="btn-primary btn-pill !px-8 !py-4">
            {accessToken ? 'ورود به حساب' : 'ورود / ثبت‌نام'} <ArrowLeft size={18} />
          </button>
        </div>
      </div>
    </section>
  );
}
