// "اتصال حساب‌های من" (docs/25 section 8.3): every login method of the person, add Google / e-mail / Telegram, remove one with
// re-authentication, resolve a link conflict explicitly, and ask for the wallet consolidation. Core decides everything; this only shows it.
import { useCallback, useEffect, useState } from 'react';
import { GoogleSignInButton } from '../GoogleSignIn.tsx';
import { Loading, PasswordInput, fd } from '../ui.tsx';
import { J, card, btn, inp } from './DashboardAccounts.tsx';
import { msgOf } from './DashboardTickets.tsx';
import type { Json } from '../types';

const IDENTITY = '/api/v1/identity';
const PROVIDER = { telegram: 'تلگرام', google: 'Google', email: 'ایمیل' } as Record<string, string>;
const newKey = () => `ui-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;

export default function LinkedAccounts({
  coreFetch,
  notify,
  reload,
}: {
  coreFetch?: Json;
  notify?: Json;
  reload?: Json;
}) {
  const [data, setData] = useState<Json>(null);
  const [method, setMethod] = useState('session');
  const [conflict, setConflict] = useState<Json>(null);
  const [tg, setTg] = useState<Json>(null);
  const [email, setEmail] = useState('');
  const [mailCode, setMailCode] = useState('');
  const [mailSent, setMailSent] = useState(false);
  const [unlinking, setUnlinking] = useState<Json>(null);
  const [proof, setProof] = useState('');
  const [googleProof, setGoogleProof] = useState('');
  const [cons, setCons] = useState<Json>([]);
  const post = (p: string, body?: Json) =>
    coreFetch(`${IDENTITY}${p}`, { method: 'POST', headers: J, body: body ? JSON.stringify(body) : undefined });

  const load = useCallback(async () => {
    const [a, m, c] = await Promise.all([
      coreFetch(`${IDENTITY}/linked-accounts`),
      coreFetch(`${IDENTITY}/reauth`),
      coreFetch(`${IDENTITY}/consolidation-status`),
    ]);
    if (a.ok) setData(await a.json());
    if (m.ok) setMethod((await m.json()).method);
    if (c.ok) setCons(await c.json());
  }, [coreFetch]);
  useEffect(() => {
    load();
  }, [load]);

  /** A 409 IDENTITY_IN_USE carries the operation the user must confirm: never merged silently. */
  async function failed(r: Json, fallback: string) {
    const d = await r
      .clone()
      .json()
      .catch(() => null);
    if (d?.error?.code === 'IDENTITY_IN_USE' && d.error.details?.operation_id) {
      setConflict(d.error.details.operation_id);
      return;
    }
    notify(await msgOf(r, fallback));
  }
  async function linkGoogle(idToken: string) {
    const r = await post('/link/google', { id_token: idToken });
    if (r.ok) {
      notify('حساب Google متصل شد');
      load();
      reload?.();
    } else await failed(r, 'اتصال Google ناموفق بود');
  }
  async function startEmail() {
    const r = await post('/link/email/start', { email });
    r.ok ? setMailSent(true) : await failed(r, 'ارسال کد ناموفق بود');
  }
  async function confirmEmail() {
    const r = await post('/link/email/confirm', { email, code: mailCode });
    if (r.ok) {
      notify('ایمیل متصل شد');
      setMailSent(false);
      setEmail('');
      setMailCode('');
      load();
    } else await failed(r, 'کد نادرست است');
  }
  async function startTelegram() {
    const r = await post('/link/telegram/start');
    r.ok ? setTg(await r.json()) : await failed(r, 'ساخت کد ناموفق بود');
  }
  async function resolve(kind: 'confirm' | 'reject') {
    const r = await post(`/link/${kind}`, { operation_id: conflict });
    if (r.ok) {
      notify(kind === 'confirm' ? 'حساب‌ها یکی شدند' : 'اتصال رد شد');
      setConflict(null);
      load();
      reload?.();
    } else await failed(r, 'عملیات ناموفق بود');
  }
  async function unlink() {
    const body: Json = { identity_id: unlinking.id };
    if (method === 'password') body.current_password = proof;
    if (method === 'email_code' || method === 'telegram_code') body.reauth_code = proof;
    if (method === 'google') body.google_id_token = googleProof;
    const r = await post('/unlink', body);
    if (r.ok) {
      notify('روش ورود قطع شد');
      setUnlinking(null);
      setProof('');
      setGoogleProof('');
      load();
    } else await failed(r, 'قطع اتصال ناموفق بود');
  }
  async function sendReauth() {
    const viaTelegram = method === 'telegram_code';
    const r = await post(`/reauth/${viaTelegram ? 'telegram' : 'email'}/start`);
    notify(
      r.ok
        ? viaTelegram
          ? 'کد به ربات تلگرام شما ارسال شد'
          : 'کد به ایمیل شما ارسال شد'
        : await msgOf(r, 'ارسال کد ناموفق بود'),
    );
  }
  async function consolidate() {
    const r = await post('/consolidation', { idempotency_key: newKey() });
    if (r.ok) {
      notify('درخواست یکپارچه‌سازی ثبت شد و پس از بررسی اجرا می‌شود');
      load();
    } else await failed(r, 'درخواست ناموفق بود');
  }

  if (!data) return <Loading />;
  const accounts = data.accounts || [];
  const open = cons.find((c: Json) => ['pending_approval', 'running'].includes(c.status));
  return (
    <div className="space-y-5">
      <div className={card}>
        <h4 className="font-extrabold">اتصال حساب‌های من</h4>
        <p className="mt-2 text-sm leading-7 text-muted">
          همهٔ روش‌های ورودتان به یک پروفایل تعلق دارد. اتصال فقط با تأیید مالکیت انجام می‌شود و پولی جابه‌جا نمی‌کند.
        </p>
        <ul className="mt-3 divide-y divide-line">
          {(data.identities || []).map((i: Json) => (
            <li key={i.id} className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm">
              <span>
                <b>{PROVIDER[i.provider] || i.provider}</b> <span className="latin text-muted">{i.label}</span>
                <span className="mr-2 text-xs text-muted">
                  {i.verified ? 'تأییدشده' : 'تأییدنشده'} · {fd(i.linked_at)}
                </span>
              </span>
              <button className="text-coral" onClick={() => setUnlinking(i)}>
                قطع اتصال
              </button>
            </li>
          ))}
        </ul>
      </div>

      {conflict && (
        <div className={`${card} border-coral`} role="alert">
          <b>این روش ورود به پروفایل دیگری تعلق دارد.</b>
          <p className="mt-2 text-sm text-muted">فقط اگر هر دو حساب مال خود شماست ادغام را تأیید کنید.</p>
          <div className="mt-3 flex gap-2">
            <button className={btn} onClick={() => resolve('confirm')}>
              تأیید اتصال
            </button>
            <button className="rounded-xl border border-line px-4 py-2" onClick={() => resolve('reject')}>
              رد
            </button>
          </div>
        </div>
      )}

      {unlinking && (
        <div className={card} role="dialog" aria-label="تأیید قطع اتصال">
          <b>قطع {PROVIDER[unlinking.provider] || unlinking.provider}</b>
          {method === 'password' && (
            <PasswordInput
              aria-label="رمز فعلی"
              className={`${inp} mt-3`}
              value={proof}
              onChange={(e: Json) => setProof(e.target.value)}
              placeholder="رمز فعلی"
            />
          )}
          {(method === 'email_code' || method === 'telegram_code') && (
            <div className="mt-3 flex gap-2">
              <input
                aria-label={method === 'email_code' ? 'کد ایمیل' : 'کد تلگرام'}
                className={inp}
                value={proof}
                onChange={(e) => setProof(e.target.value)}
                placeholder={method === 'email_code' ? 'کد ایمیل' : 'کد تلگرام'}
              />
              <button className="rounded-xl border border-line px-3" onClick={sendReauth}>
                ارسال کد
              </button>
            </div>
          )}
          {method === 'google' && (
            <div className="mt-3">
              <p className="text-sm text-muted">برای ادامه، دوباره با یکی از حساب‌های Google متصل خود تأیید کنید.</p>
              {googleProof ? (
                <p className="mt-2 text-sm font-bold">تأیید Google دریافت شد.</p>
              ) : (
                <GoogleSignInButton onCredential={setGoogleProof} text="continue_with" className="mt-2" />
              )}
            </div>
          )}
          <div className="mt-3 flex gap-2">
            <button className={btn} onClick={unlink}>
              تأیید قطع اتصال
            </button>
            <button className="rounded-xl border border-line px-4 py-2" onClick={() => setUnlinking(null)}>
              انصراف
            </button>
          </div>
        </div>
      )}

      <div className="grid gap-5 md:grid-cols-2">
        <div className={card}>
          <h4 className="font-extrabold">افزودن حساب Google</h4>
          <GoogleSignInButton onCredential={linkGoogle} text="continue_with" className="mt-3" />
        </div>
        <div className={card}>
          <h4 className="font-extrabold">اتصال تلگرام</h4>
          {tg ? (
            <div className="mt-3 text-sm leading-7">
              کد: <b className="latin">{tg.code}</b> ({Math.round(tg.expires_in / 60)} دقیقه، یک‌بارمصرف)
              {tg.replace && <div className="text-coral">این کار تلگرام فعلی را جایگزین می‌کند.</div>}
              {tg.telegram_deeplink && (
                <a
                  href={tg.telegram_deeplink}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={`${btn} mt-3 block text-center`}
                >
                  باز کردن در تلگرام
                </a>
              )}
            </div>
          ) : (
            <button className={`${btn} mt-3`} onClick={startTelegram}>
              ساخت کد اتصال
            </button>
          )}
        </div>
        <div className={card}>
          <h4 className="font-extrabold">افزودن ایمیل</h4>
          <input
            aria-label="ایمیل جدید"
            className={`${inp} mt-3 latin`}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="email@example.com"
          />
          {mailSent ? (
            <>
              <input
                aria-label="کد تأیید"
                className={`${inp} mt-2`}
                value={mailCode}
                onChange={(e) => setMailCode(e.target.value)}
                placeholder="کد تأیید"
              />
              <button className={`${btn} mt-3`} onClick={confirmEmail}>
                تأیید ایمیل
              </button>
            </>
          ) : (
            <button className={`${btn} mt-3`} disabled={!email.includes('@')} onClick={startEmail}>
              ارسال کد
            </button>
          )}
        </div>
        <div className={card}>
          <h4 className="font-extrabold">یکپارچه‌سازی کیف پول</h4>
          {accounts.length > 1 ? (
            open ? (
              <p className="mt-2 text-sm text-muted">
                درخواست شما ({open.status === 'running' ? 'در حال اجرا' : 'در انتظار تأیید'}) در حال بررسی است.
              </p>
            ) : (
              <>
                <p className="mt-2 text-sm leading-7 text-muted">
                  {accounts.length} حساب به این پروفایل متصل است. موجودی‌ها از طریق دفترکل و پس از بررسی مدیر منتقل
                  می‌شوند.
                </p>
                <button className={`${btn} mt-3`} onClick={consolidate}>
                  درخواست یکپارچه‌سازی
                </button>
              </>
            )
          ) : (
            <p className="mt-2 text-sm text-muted">فقط یک حساب دارید؛ چیزی برای یکپارچه‌سازی نیست.</p>
          )}
        </div>
      </div>
    </div>
  );
}
