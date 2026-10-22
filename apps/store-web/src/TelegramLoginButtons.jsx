// TelegramLoginButtons.jsx — the Telegram entries of the storefront login dialog.
// Two methods, switched on independently in Admin > Settings > Login with Telegram:
//   direct — redirect to Telegram's own OpenID Connect page (the server handles the whole flow, see telegram_oidc_router.py);
//   bot    — approve inside the store's bot (TelegramLogin.jsx, opened through onBot).
// With both on, "direct" is the primary action and "bot" the outlined fallback (it also works when oauth.telegram.org is blocked
// in the visitor's network). With only one on, it is the single primary button.

import { useEffect, useState } from 'react';
import { Bot, Loader2, Send } from 'lucide-react';

export default function TelegramLoginButtons({ base, storeId, bot, direct, onBot }) {
  const [going, setGoing] = useState(false);
  // Coming back with the browser's Back button restores this page from the bfcache with the spinner still on.
  useEffect(() => {
    const reset = (e) => {
      if (e.persisted) setGoing(false);
    };
    window.addEventListener('pageshow', reset);
    return () => window.removeEventListener('pageshow', reset);
  }, []);
  if (!bot && !direct) return null;

  const href = `${base}/api/v1/auth/telegram/oidc/start?store_id=${encodeURIComponent(storeId)}`;
  const hint =
    direct && bot
      ? '«ورود سریع» شما را به صفحهٔ رسمی تلگرام می‌برد؛ «تأیید در ربات» ورود را با انتخاب یک عدد داخل ربات تأیید می‌کند.'
      : direct
        ? 'به صفحهٔ رسمی تلگرام می‌روید و با یک تأیید برمی‌گردید؛ رمز یا کد پیامکی لازم نیست.'
        : 'ربات تلگرام باز می‌شود و ورود را با یک عدد تأیید می‌کنید؛ رمز یا کد پیامکی لازم نیست.';

  return (
    <div className="mt-6 space-y-2.5">
      {direct && (
        <a
          href={href}
          rel="nofollow"
          onClick={() => setGoing(true)}
          aria-busy={going}
          aria-disabled={going}
          className={`btn-tg w-full ${going ? 'pointer-events-none opacity-80' : ''}`}
        >
          {going ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
          {going ? 'در حال انتقال به تلگرام…' : bot ? 'ورود سریع با تلگرام' : 'ورود با تلگرام'}
        </a>
      )}
      {bot && (
        <button type="button" onClick={onBot} className={`${direct ? 'btn-tg-outline' : 'btn-tg'} w-full`}>
          {direct ? <Bot size={18} /> : <Send size={18} />}
          {direct ? 'تأیید در ربات تلگرام' : 'ورود با تلگرام'}
        </button>
      )}
      <p className="px-1 text-center text-[11px] leading-5 text-muted">{hint}</p>
    </div>
  );
}
