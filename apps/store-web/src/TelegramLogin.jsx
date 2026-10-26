// TelegramLogin.jsx — website login approved inside the Telegram bot (docs/TELEGRAM-WEB-LOGIN.md).
// The browser starts a session, shows a deep link / QR code and a number-matching code, then polls with a secret
// poll token (POST body, never a URL) until the bot approves. Nothing secret is persisted: tokens stay in memory.

import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowRight, Loader2, RefreshCw, Send, ShieldCheck, ShieldX } from 'lucide-react';

const REASONS = {
  user_denied: 'ورود در تلگرام رد شد.',
  cancelled: 'درخواست ورود لغو شد.',
  too_many_wrong_choices: 'عدد اشتباه انتخاب شد؛ برای امنیت شما این درخواست بسته شد.',
  admin_use_panel: 'ورود ادمین فقط از پنل مدیریت انجام می‌شود.',
  account_disabled: 'حساب شما غیرفعال است. با پشتیبانی تماس بگیرید.',
  registration_closed: 'ثبت‌نام جدید موقتاً بسته است.',
  rate_limited: 'تلاش‌ها زیاد بود؛ کمی بعد دوباره امتحان کنید.',
  login_disabled: 'ورود با تلگرام موقتاً غیرفعال شده است.',
};
// Trusted-device key (docs/21-Automatic-Identity-Verification.md): a random value that never leaves this browser except
// toward our own API, which stores only its SHA-256. It lets the next login skip the number match, or the bot entirely.
const KEY_NAME = 'melorin.device_key';
const KEY_OK = /^[A-Za-z0-9_-]{32,128}$/;
export function getDeviceKey(create = true) {
  try {
    const have = localStorage.getItem(KEY_NAME);
    if (have && KEY_OK.test(have)) return have;
    if (!create) return null;
    const bytes = crypto.getRandomValues(new Uint8Array(32));
    const key = btoa(String.fromCharCode(...bytes))
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=+$/, '');
    localStorage.setItem(KEY_NAME, key);
    return key;
  } catch {
    return null; // private mode / storage blocked: the login simply stays on the manual path
  }
}
// Sign-out on a shared computer: drop trust on the server and forget the key here.
export async function forgetDevice(base) {
  const key = getDeviceKey(false);
  if (!key) return;
  try {
    localStorage.removeItem(KEY_NAME);
  } catch {
    /* storage blocked */
  }
  try {
    await fetch(`${base}/api/v1/auth/telegram/web/devices/forget`, {
      method: 'POST',
      credentials: 'include',
      keepalive: true,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device_key: key }),
    });
  } catch {
    /* best effort: the trust also expires on its own */
  }
}
const mmss = (s) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;

export default function TelegramLogin({ base, storeId, onTokens, onBack }) {
  const [phase, setPhase] = useState('starting'); // starting | waiting | done | denied | expired | error
  const [session, setSession] = useState(null);
  const [left, setLeft] = useState(0);
  const [reason, setReason] = useState('');
  const alive = useRef(true);
  const timer = useRef(0);
  const ctrl = useRef(null);
  const fails = useRef(0);
  const deadline = useRef(0);
  const live = useRef(null); // session currently polled (also used for cancel on unmount)
  const finished = useRef(false);
  const gen = useRef(0); // a slower, older start() must never overwrite a newer session
  const api = `${base}/api/v1/auth/telegram/web`;

  const stop = useCallback(() => {
    clearTimeout(timer.current);
    ctrl.current?.abort();
  }, []);

  const poll = useCallback(
    async (s) => {
      if (!alive.current || live.current !== s) return;
      const again = (ms) => {
        timer.current = setTimeout(() => poll(s), ms);
      };
      ctrl.current = new AbortController();
      try {
        const r = await fetch(`${api}/sessions/${encodeURIComponent(s.session_id)}/poll`, {
          method: 'POST',
          credentials: 'include',
          cache: 'no-store',
          signal: ctrl.current.signal,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ poll_token: s.poll_token }),
        });
        if (r.status === 404 || r.status === 410) {
          setPhase('expired');
          return;
        }
        if (r.status === 429) {
          again(6000);
          return;
        }
        if (!r.ok) throw new Error('poll');
        fails.current = 0;
        const d = await r.json();
        if (d.tokens) {
          finished.current = true;
          setPhase('done');
          onTokens(d.tokens);
          return;
        }
        if (d.status === 'denied') {
          setReason(d.reason || '');
          setPhase('denied');
          return;
        }
        if (d.status === 'expired' || d.status === 'consumed') {
          setPhase('expired');
          return;
        }
        if (d.expires_in) deadline.current = Date.now() + d.expires_in * 1000;
        if (d.match_code || d.level) {
          // A trusted-browser attempt fell back to the manual number match: show the number now.
          const next = {
            ...live.current,
            level: d.level || live.current.level,
            match_code: d.match_code || live.current.match_code,
          };
          live.current = next;
          setSession(next);
          s = next;
        }
        again(Math.max(1, s.poll_interval || 2) * 1000);
      } catch (e) {
        if (e?.name === 'AbortError' || !alive.current) return;
        fails.current += 1;
        if (fails.current > 6) {
          setPhase('error');
          return;
        }
        again(Math.min(10000, 1500 * 2 ** fails.current));
      }
    },
    [api, onTokens],
  );

  const start = useCallback(async () => {
    stop();
    live.current = null;
    fails.current = 0;
    finished.current = false;
    const g = ++gen.current;
    setPhase('starting');
    setReason('');
    setSession(null);
    try {
      const r = await fetch(`${api}/sessions`, {
        method: 'POST',
        credentials: 'include',
        cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ store_id: storeId || null, device_key: getDeviceKey(), remember: true }),
      });
      if (g !== gen.current) return;
      if (!r.ok) {
        let msg = '';
        try {
          msg = (await r.json())?.error?.message || '';
        } catch {
          /* non-JSON error */
        }
        setReason(msg);
        setPhase('error');
        return;
      }
      const s = await r.json();
      if (!alive.current || g !== gen.current) return;
      live.current = s;
      deadline.current = Date.now() + s.expires_in * 1000;
      setSession(s);
      setLeft(s.expires_in);
      setPhase('waiting');
      poll(s);
    } catch {
      if (alive.current && g === gen.current) setPhase('error');
    }
  }, [api, storeId, poll, stop]);

  useEffect(() => {
    alive.current = true;
    start();
    // Returning from the Telegram app: poll right away instead of waiting for the next tick.
    const onVisible = () => {
      if (document.visibilityState === 'visible' && live.current && !finished.current) {
        clearTimeout(timer.current);
        poll(live.current);
      }
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      alive.current = false;
      stop();
      document.removeEventListener('visibilitychange', onVisible);
      const s = live.current;
      // Closing the dialog invalidates the link that is still sitting in Telegram.
      if (s && !finished.current)
        fetch(`${api}/sessions/${encodeURIComponent(s.session_id)}/cancel`, {
          method: 'POST',
          keepalive: true,
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ poll_token: s.poll_token }),
        }).catch(() => {});
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (phase !== 'waiting') return;
    const t = setInterval(() => {
      const s = Math.max(0, Math.ceil((deadline.current - Date.now()) / 1000));
      setLeft(s);
      if (s === 0) {
        stop();
        setPhase('expired');
      }
    }, 1000);
    return () => clearInterval(t);
  }, [phase, stop]);

  const retry = (
    <button type="button" onClick={start} className="btn-primary mt-5 w-full">
      <RefreshCw size={17} />
      دوباره امتحان کن
    </button>
  );
  const back = onBack && (
    <button
      type="button"
      onClick={onBack}
      className="mt-3 flex w-full items-center justify-center gap-1.5 text-xs font-bold text-muted hover:text-ink"
    >
      <ArrowRight size={14} />
      روش‌های دیگر ورود
    </button>
  );

  if (phase === 'starting')
    return (
      <div className="mt-6 space-y-3" role="status" aria-label="در حال آماده‌سازی">
        <div className="skeleton h-12" />
        <div className="skeleton h-24" />
      </div>
    );

  if (phase === 'waiting' && session)
    return (
      <div>
        <p className="mt-2 text-sm leading-7 text-muted">
          {session.level === 'silent'
            ? 'این دستگاه را می‌شناسیم؛ در حال ورود خودکار… نیازی به هیچ کاری نیست.'
            : session.level === 'auto'
              ? 'این دستگاه قبلاً تأیید شده؛ فقط ربات را باز کن، همان لحظه وارد می‌شوی و عدد یا دکمه‌ای لازم نیست.'
              : 'ربات تلگرام را باز کن و ورود را تأیید کن؛ نه رمز لازم است، نه کد پیامکی.'}
        </p>
        {session.level !== 'silent' && (
          <a
            href={session.deeplink}
            target="_blank"
            rel="noopener noreferrer"
            className="btn-primary mt-5 w-full !bg-[#229ED9] !text-white"
          >
            <Send size={18} />
            باز کردن ربات تلگرام
          </a>
        )}
        {session.match_code && (
          <div className="mt-5 rounded-2xl bg-surface2 p-4 text-center">
            <div className="text-xs font-bold text-muted">در ربات، همین عدد را انتخاب کن</div>
            <div
              className="latin mt-1 text-5xl font-black tracking-[.25em] text-ink"
              aria-label={`عدد تأیید: ${session.match_code.split('').join(' ')}`}
            >
              {session.match_code}
            </div>
          </div>
        )}
        {session.qr && (
          <div className="mt-5 hidden items-center gap-4 sm:flex">
            <img
              src={session.qr}
              alt="کد QR ورود با تلگرام"
              width="112"
              height="112"
              className="h-28 w-28 shrink-0 rounded-xl ring-1 ring-line"
            />
            <p className="text-xs leading-6 text-muted">
              روی کامپیوتر هستی؟ دوربین گوشی یا تلگرام را روی این کد بگیر تا ربات باز شود.
            </p>
          </div>
        )}
        <div className="mt-5 flex items-center justify-between text-xs text-muted" role="status" aria-live="polite">
          <span className="flex items-center gap-1.5">
            <Loader2 size={14} className="animate-spin" />
            در انتظار تأیید در تلگرام…
          </span>
          <span className="latin font-bold">{mmss(left)}</span>
        </div>
        <p className="mt-4 flex items-start gap-1.5 text-[11px] leading-5 text-muted">
          <ShieldCheck size={14} className="mt-0.5 shrink-0" />
          ربات دستگاه و آی‌پی این درخواست را نشان می‌دهد. اگر کسی از تو خواست این‌جا چیزی تأیید کنی، «این من نبودم» را
          بزن.
        </p>
        {back}
      </div>
    );

  if (phase === 'done')
    return (
      <div className="mt-6 flex flex-col items-center gap-2 py-6 text-center" role="status">
        <span className="grid h-14 w-14 place-items-center rounded-full bg-mint-soft text-mint">
          <ShieldCheck size={28} />
        </span>
        <p className="font-extrabold">ورود تأیید شد</p>
      </div>
    );

  const text =
    phase === 'denied'
      ? REASONS[reason] || 'ورود انجام نشد.'
      : phase === 'expired'
        ? 'زمان این درخواست تمام شد.'
        : reason || 'اتصال برقرار نشد. اینترنت را بررسی کن و دوباره امتحان کن.';
  return (
    <div className="mt-6 text-center" role="alert">
      <span className="mx-auto grid h-14 w-14 place-items-center rounded-full bg-danger-soft text-danger">
        <ShieldX size={28} />
      </span>
      <p className="mt-3 text-sm font-bold leading-7">{text}</p>
      {reason !== 'admin_use_panel' && retry}
      {back}
    </div>
  );
}
