/** Docs/25 section 8.2: a visible entry point on the landing page; opens the dashboard on the linking tab. */
import { LINKING_TAB_KEY } from './linkingTab.ts';
import type { Json } from './types';

export default function LinkAccountsSection({ goAccount }: { goAccount?: Json }) {
  const open = () => {
    try {
      sessionStorage.setItem(LINKING_TAB_KEY, 'linking');
    } catch {
      /* storage blocked: the user simply lands on the default tab */
    }
    goAccount?.();
  };
  return (
    <section id="link-accounts" className="mx-auto max-w-6xl px-5 pb-24">
      <div className="card flex flex-wrap items-center justify-between gap-5 !p-8">
        <div className="max-w-xl">
          <h2 className="text-2xl font-black">همه حساب‌هایت را یکپارچه کن</h2>
          <p className="mt-3 leading-8 text-muted">
            حساب تلگرام، Google و ایمیل خود را به یک پروفایل متصل کن و از یک کیف پول و تاریخچه سفارش مشترک استفاده کن.
          </p>
        </div>
        <button onClick={open} className="btn-primary btn-pill !px-8 !py-4">
          اتصال حساب‌های من
        </button>
      </div>
    </section>
  );
}
