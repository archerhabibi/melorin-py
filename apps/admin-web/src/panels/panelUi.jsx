import { useState } from 'react';
import { capacityLabel } from '../targets.js';
import { usage } from '../infra.jsx';
import { SegMeter, capTone, num } from '../kit.jsx';
import { Bot, FlaskConical, Server, ServerCog, ShieldCheck, X } from 'lucide-react';

// ---------- helpers ----------
const STALE_MS = 24 * 3600 * 1000;
const rtf = new Intl.RelativeTimeFormat('fa', { numeric: 'auto' });
export function ago(v) {
  if (!v) return 'هرگز';
  const s = Math.round((new Date(v).getTime() - Date.now()) / 1000),
    a = Math.abs(s);
  if (a < 60) return rtf.format(s, 'second');
  if (a < 3600) return rtf.format(Math.round(s / 60), 'minute');
  if (a < 86400) return rtf.format(Math.round(s / 3600), 'hour');
  return rtf.format(Math.round(s / 86400), 'day');
}
export const isStale = (p) => !p.last_health_at || Date.now() - new Date(p.last_health_at).getTime() > STALE_MS;

export const KINDS = {
  sanaei: { title: 'سنایی (3x-ui)', desc: 'پنل 3x-ui / Sanaei با Inbound و ساب‌اسکریپشن', Icon: ServerCog, tone: 'in' },
  pasarguard: { title: 'پاسارگارد', desc: 'PasarGuard با گروه‌ها یا قالب کاربر', Icon: ShieldCheck, tone: 'ok' },
  upstream_bot: {
    title: 'ربات واسط (Upstream Bot)',
    desc: 'خرید، تمدید و مرجوعی از یک ربات تلگرامی والد که API ندارد',
    Icon: Bot,
    tone: 'ac',
  },
  // Mock is only available in dev builds; backend rejects mock panels in production.
  ...(import.meta.env.DEV
    ? {
        mock: {
          title: 'Mock (آزمایشی)',
          desc: 'فقط برای توسعه و تست؛ در محیط عملیاتی غیرفعال است',
          Icon: FlaskConical,
          tone: 'wn',
        },
      }
    : {}),
};
export const kindOf = (k) => KINDS[k] || { title: k, desc: '', Icon: Server, tone: 'mu' };

// ---------- small UI parts ----------
export function Chips({ values, onChange, placeholder }) {
  const [t, setT] = useState('');
  const add = () => {
    const n = parseInt(t, 10);
    if (Number.isInteger(n) && n > 0 && !values.includes(n)) onChange([...values, n]);
    setT('');
  };
  return (
    <div className="inp flex flex-wrap items-center gap-1.5 !py-1.5" dir="ltr">
      {values.map((n) => (
        <span
          key={n}
          className="inline-flex items-center gap-1 rounded-md bg-[var(--mb)] px-2 py-0.5 text-xs font-bold"
        >
          {n}
          <button type="button" aria-label={`حذف ${n}`} onClick={() => onChange(values.filter((x) => x !== n))}>
            <X size={12} />
          </button>
        </span>
      ))}
      <input
        inputMode="numeric"
        className="min-w-[6rem] flex-1 bg-transparent py-1 text-sm outline-hidden"
        value={t}
        placeholder={values.length ? '' : placeholder}
        onChange={(e) => setT(e.target.value.replace(/\D/g, ''))}
        onBlur={add}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ',') {
            e.preventDefault();
            add();
          } else if (e.key === 'Backspace' && !t && values.length) onChange(values.slice(0, -1));
        }}
      />
    </div>
  );
}

export function Meter({ s, panelKind }) {
  const u = usage(s),
    t = capTone(u);
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between text-xs">
        <span className="text-[var(--mu)]">{capacityLabel(panelKind, s.target)}</span>
        <span className="num font-bold">
          <span style={{ color: `var(--${t})` }}>{num(s.active_accounts)}</span> از {num(s.capacity)}
          <span className="mr-1.5 font-normal text-[var(--mu)]">({num(Math.round(u * 100))}٪)</span>
        </span>
      </div>
      <SegMeter value={u} tone={t} max={s.capacity} now={s.active_accounts} label="میزان استفاده از ظرفیت" />
    </div>
  );
}
