// Reseller panel › PasarGuard admin. Every store has its OWN Operator admin on each VPN panel; all accounts sold here live under it.
// The reseller sees it read-only (never a password) and may ask the platform admin to change its optional "Profile & contact".
// The admin reviews each request, so nothing here can write to the panel directly and only one request can wait at a time.
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Send, ServerCog, UserCog, XCircle } from 'lucide-react';
import { Empty, Loading, StatusBadge, fd } from './ui.jsx';

const J = { 'Content-Type': 'application/json' };
// the four fields a reseller may ask for (Core's REQUESTABLE_FIELDS); sub_domain and the internal note stay admin-only
export const FIELDS = [
  ['profile_title', 'عنوان پروفایل', 'نام نمایشی ادمین شما در صفحهٔ اشتراک مشتری.'],
  ['support_url', 'لینک پشتیبانی', 'آدرس https://… یا tg://… ؛ خالی‌گذاشتن آن را پاک می‌کند.'],
  ['telegram_id', 'آیدی عددی تلگرام', 'فقط عدد. پس از ثبت فقط قابل تغییر است و پاک نمی‌شود.'],
  ['discord_webhook', 'وبهوک دیسکورد', 'فقط آدرس https://discord.com/api/webhooks/… ؛ خالی‌گذاشتن آن را پاک می‌کند.'],
];
const LABEL = Object.fromEntries(FIELDS.map(([k, l]) => [k, l]));
const shown = (v) => (v === undefined || v === null || v === '' ? '—' : String(v));
// a webhook URL is a secret: it is never echoed back in full, even to its own owner
const display = (k, v) => (k === 'discord_webhook' && v ? `${String(v).slice(0, 32)}…` : shown(v));
const ltr = (v) => (
  <span dir="ltr" className="latin break-all text-xs">
    {v}
  </span>
);

async function reason(r, fallback) {
  const d = await r.json().catch(() => ({}));
  return d?.error?.message || d?.detail || fallback;
}

function AdminCard({ a }) {
  return (
    <div className="card space-y-3" data-testid="panel-admin-card">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="flex items-center gap-2 font-extrabold">
          <ServerCog size={18} aria-hidden="true" /> {a.panel_name || 'پنل'}
        </h4>
        <StatusBadge status={a.status} />
      </div>
      <dl className="grid gap-3 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-xs text-muted">نام کاربری ادمین شما</dt>
          <dd className="mt-1">{ltr(a.username)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted">نقش</dt>
          <dd className="mt-1">{ltr(a.role)}</dd>
        </div>
        {FIELDS.map(([k, l]) => (
          <div key={k}>
            <dt className="text-xs text-muted">{l}</dt>
            <dd className="mt-1">{ltr(display(k, a.profile?.[k]))}</dd>
          </div>
        ))}
      </dl>
      {a.status === 'error' && (
        <p className="text-xs text-danger" role="alert">
          راه‌اندازی ادمین شما روی این پنل با خطا روبه‌رو شد؛ به‌صورت خودکار دوباره تلاش می‌شود. اگر ادامه یافت به
          پشتیبانی بگویید.
        </p>
      )}
      {a.status === 'active' && a.profile_synced === false && (
        <p className="text-xs text-muted">تغییر پروفایل ثبت شده و هنوز روی پنل اعمال نشده؛ تلاش خودکار ادامه دارد.</p>
      )}
    </div>
  );
}

function RequestForm({ current, onSent, coreFetch, base, notify }) {
  const init = useMemo(
    () => Object.fromEntries(FIELDS.map(([k]) => [k, current?.[k] == null ? '' : String(current[k])])),
    [current],
  );
  const [form, setForm] = useState(init);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  // an emptied Telegram ID is "unchanged": Core and the panel cannot clear it, so it is never sent
  const changed = FIELDS.map(([k]) => k).filter(
    (k) => form[k].trim() !== init[k] && !(k === 'telegram_id' && !form[k].trim()),
  );
  const badTelegram = form.telegram_id.trim() !== '' && !/^\d+$/.test(form.telegram_id.trim());
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  async function send() {
    setBusy(true);
    setError('');
    try {
      const changes = Object.fromEntries(
        changed.map((k) => [k, k === 'telegram_id' ? Number(form[k]) : form[k].trim()]),
      );
      const r = await coreFetch(`${base}/panel-admin/change-requests`, {
        method: 'POST',
        headers: J,
        body: JSON.stringify({ changes, message: message.trim() || null }),
      });
      if (!r.ok) {
        setError(await reason(r, 'ثبت درخواست ناموفق بود'));
        return;
      }
      notify('درخواست شما برای بررسی به ادمین ارسال شد');
      setMessage('');
      onSent();
    } catch {
      setError('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card space-y-4" data-testid="change-request-form">
      <div>
        <h4 className="flex items-center gap-2 font-extrabold">
          <UserCog size={18} aria-hidden="true" /> درخواست تغییر پروفایل و اطلاعات تماس
        </h4>
        <p className="mt-1 text-xs text-muted">
          این بخش اختیاری است. تغییر را مستقیم روی پنل نمی‌زنید؛ ادمین بررسی می‌کند و نتیجه را به شما اطلاع می‌دهد.
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {FIELDS.map(([k, l, hint]) => (
          <label key={k} className="text-sm">
            {l}
            <input
              className="input latin mt-1 text-left"
              dir="ltr"
              inputMode={k === 'telegram_id' ? 'numeric' : 'text'}
              aria-invalid={(k === 'telegram_id' && badTelegram) || undefined}
              value={form[k]}
              onChange={(e) => set(k, e.target.value)}
            />
            <span className="mt-1 block text-xs text-muted">{hint}</span>
          </label>
        ))}
      </div>
      <label className="block text-sm">
        توضیح برای ادمین (اختیاری)
        <textarea
          className="input mt-1"
          rows={2}
          maxLength={500}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
        />
      </label>
      {error && (
        <p className="text-sm text-danger" role="alert">
          {error}
        </p>
      )}
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs text-muted">
          {changed.length ? `${changed.length} مورد تغییر کرده` : 'هنوز چیزی تغییر نکرده'}
        </span>
        <button className="btn-primary" disabled={busy || !changed.length || badTelegram} onClick={send}>
          <Send size={15} aria-hidden="true" /> {busy ? 'در حال ارسال…' : 'ارسال درخواست'}
        </button>
      </div>
    </div>
  );
}

function RequestCard({ r, onCancel, busy }) {
  return (
    <div className="card space-y-2" data-testid={`request-${r.status}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <StatusBadge status={r.status} />
        <span className="text-xs text-muted">{fd(r.created_at)}</span>
      </div>
      <ul className="space-y-1 text-sm">
        {Object.entries(r.changes || {}).map(([k, v]) => (
          <li key={k} className="flex flex-wrap gap-2">
            <span className="text-muted">{LABEL[k] || k}:</span>
            {ltr(display(k, v))}
          </li>
        ))}
      </ul>
      {r.message && <p className="text-xs text-muted">پیام شما: {r.message}</p>}
      {r.review_note && <p className="text-xs">توضیح ادمین: {r.review_note}</p>}
      {r.status === 'pending' && (
        <button className="btn-soft" disabled={busy} onClick={() => onCancel(r.id)}>
          <XCircle size={15} aria-hidden="true" /> لغو درخواست
        </button>
      )}
    </div>
  );
}

export default function ResellerPanelAdmin({ coreFetch, base, notify }) {
  const [admins, setAdmins] = useState(null);
  const [requests, setRequests] = useState(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [a, b] = await Promise.all([
        coreFetch(`${base}/panel-admin`),
        coreFetch(`${base}/panel-admin/change-requests`),
      ]);
      if (!a.ok || !b.ok) throw new Error('load');
      setAdmins(await a.json());
      setRequests(await b.json());
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [coreFetch, base]);
  useEffect(() => {
    load();
  }, [load]);

  async function cancel(id) {
    setBusy(true);
    try {
      const r = await coreFetch(`${base}/panel-admin/change-requests/${id}/cancel`, { method: 'POST' });
      notify(r.ok ? 'درخواست لغو شد' : await reason(r, 'لغو درخواست ناموفق بود'));
      await load();
    } catch {
      notify('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy(false);
    }
  }

  if (failed) return <Empty text="اطلاعات ادمین پنل در دسترس نیست." />;
  if (!admins || !requests) return <Loading rows={3} />;
  const pending = requests.find((r) => r.status === 'pending');
  const history = requests.filter((r) => r.status !== 'pending');
  return (
    <div className="space-y-4">
      <div className="card">
        <h4 className="flex items-center gap-2 font-extrabold">
          <ServerCog size={18} aria-hidden="true" /> ادمین پنل فروشگاه من
        </h4>
        <p className="mt-2 text-sm text-muted">
          روی هر پنل VPN، فروشگاه شما یک ادمین جداگانه دارد و اکانت‌های فروخته‌شده از این فروشگاه (مال شما و مشتریانتان)
          زیر همان ساخته می‌شود. ورود مستقیم به پنل با ادمین پلتفرم است و رمزی به نماینده نمایش داده نمی‌شود.
        </p>
      </div>
      {admins.length === 0 ? (
        <Empty text="ادمین شما هنوز روی پنل ساخته نشده است؛ چند دقیقه بعد دوباره سر بزنید." icon={ServerCog} />
      ) : (
        admins.map((a) => <AdminCard key={`${a.panel_name}:${a.username}`} a={a} />)
      )}
      {admins.length > 0 &&
        (pending ? (
          <>
            <p className="text-sm text-muted">
              یک درخواست در انتظار بررسی دارید؛ تا نتیجهٔ آن یا لغوش درخواست تازه‌ای ثبت نمی‌شود.
            </p>
            <RequestCard r={pending} onCancel={cancel} busy={busy} />
          </>
        ) : (
          <RequestForm current={admins[0]?.profile} onSent={load} coreFetch={coreFetch} base={base} notify={notify} />
        ))}
      {history.length > 0 && (
        <div className="space-y-3">
          <h4 className="font-extrabold">سابقهٔ درخواست‌ها</h4>
          {history.map((r) => (
            <RequestCard key={r.id} r={r} onCancel={cancel} busy={busy} />
          ))}
        </div>
      )}
    </div>
  );
}
