import {
  ArrowLeftRight,
  Clock,
  Fingerprint,
  Globe,
  Mail,
  Send,
  ShieldAlert,
  ShieldCheck,
  UserRound,
} from 'lucide-react';
import { dt, sid } from '../../shared/ui.tsx';
import { num, tint } from '../../shared/kit.tsx';
import type { Json, Rec } from '../../shared/types.ts';

export const PROVIDERS: Rec = {
  google: { label: 'Google', Icon: Globe, tone: 'in' },
  email: { label: 'ایمیل', Icon: Mail, tone: 'wn' },
  telegram: { label: 'تلگرام', Icon: Send, tone: 'ok' },
};
export const REASONS: Rec = {
  verified_email_matches_other_user: [
    'ایمیل تأییدشده متعلق به حساب دیگری است',
    'کاربر ایمیلی را تأیید کرد که از قبل به یک حساب دیگر وصل است.',
  ],
  google_account_belongs_to_other_user: [
    'حساب Google متعلق به کاربر دیگری است',
    'کاربر خواست حساب Google ای را وصل کند که قبلاً به حساب دیگری گره خورده است.',
  ],
  multiple_verified_email_users: [
    'ایمیل با چند حساب هم‌پوشانی دارد',
    'ایمیل ورودی با بیش از یک حساب موجود مطابقت دارد؛ اتصال خودکار ممکن نبود.',
  ],
  email_field_conflict: [
    'ایمیل قبلاً روی پروفایل دیگری ثبت شده',
    'ایمیل در پروفایل یک حساب قدیمی ثبت است، بدون اینکه هویت متصل داشته باشد.',
  ],
};
export const reasonOf = (r: Json) => REASONS[r] || [r || 'نامشخص', 'دلیل ثبت‌شده توسط Core.'];
export const prov = (p: Json) => PROVIDERS[p] || { label: p || '—', Icon: Fingerprint, tone: 'mu' };
export const STRIPE: Rec = { open: 'var(--wn)', dismissed: 'var(--ln)', linked: 'var(--ok)' };
export const STATUS_TEXT: Rec = { open: 'باز', dismissed: 'رد شده', linked: 'متصل شده' };
export const ago = (v: Json) => {
  if (!v) return '—';
  const m = Math.max(0, Math.round((Date.now() - new Date(v).getTime()) / 60000));
  if (m < 1) return 'همین الان';
  if (m < 60) return `${num(m)} دقیقه پیش`;
  if (m < 1440) return `${num(Math.round(m / 60))} ساعت پیش`;
  return `${num(Math.round(m / 1440))} روز پیش`;
};

export function ProviderTile({ p }: { p?: Json }) {
  const { Icon, tone } = prov(p);
  return (
    <span className="tile" style={{ width: 44, height: 44, ...tint(tone) }}>
      <Icon size={19} />
    </span>
  );
}
export const STATUS_TONE: Rec = { open: 'b-wn', dismissed: 'b-mu', linked: 'b-ok' };
export const StatusBadge = ({ s }: { s?: Json }) => (
  <span className={`badge ${STATUS_TONE[s] || 'b-mu'}`}>{STATUS_TEXT[s] || s}</span>
);

/** Compact account card used on both sides of a conflict. */
export function UserCard({ u, role, fallbackId }: { u?: Json; role?: Json; fallbackId?: Json }) {
  if (!u)
    return (
      <div className="rounded-xl border border-dashed border-[var(--ln)] p-3 text-xs text-[var(--mu)]">
        {role}: حساب <span dir="ltr">{sid(fallbackId)}</span> پیدا نشد (ممکن است حذف شده باشد).
      </div>
    );
  return (
    <div className="min-w-0 rounded-xl border border-[var(--hair)] bg-[var(--sf2)] p-3">
      <div className="flex items-center gap-2">
        <span className="tile h-8 w-8 bg-[var(--mb)] text-[var(--mu)]">
          <UserRound size={15} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[11px] font-bold text-[var(--mu)]">{role}</div>
          <div className="truncate text-sm font-extrabold">{u.display_name || 'بدون نام'}</div>
        </div>
        {u.is_guest && <span className="badge b-mu">مهمان</span>}
        {!u.is_active && <span className="badge b-bd">غیرفعال</span>}
      </div>
      <dl className="mt-2.5 grid grid-cols-2 gap-x-3 gap-y-1.5 text-[11px]">
        <dt className="text-[var(--mu)]">ایمیل</dt>
        <dd className="truncate font-bold" dir="ltr" style={{ textAlign: 'right' }}>
          {u.email || '—'}
        </dd>
        <dt className="text-[var(--mu)]">سفارش‌ها</dt>
        <dd className="num font-bold">{num(u.orders)}</dd>
        <dt className="text-[var(--mu)]">عضویت</dt>
        <dd className="font-bold">{ago(u.created_at)}</dd>
        <dt className="text-[var(--mu)]">روش‌های ورود</dt>
        <dd className="flex flex-wrap gap-1">
          {u.providers.length
            ? u.providers.map((p: Json) => (
                <span key={p} className="spec !px-1.5 !py-0.5 !text-[10px]">
                  {prov(p).label}
                </span>
              ))
            : '—'}
        </dd>
      </dl>
    </div>
  );
}

/** Hint that tells the admin how risky the decision is: an account with orders must never be thrown away blindly. */
export function Advice({ r }: { r?: Json }) {
  const heavy = (r.candidates || []).some((c: Json) => c.orders > 0) || (r.source_user?.orders || 0) > 0;
  return (
    <p
      className={`flex items-start gap-2 rounded-xl p-3 text-xs leading-6 ${heavy ? 'bg-[var(--wnb)] text-[var(--wn)]' : 'bg-[var(--inb)] text-[var(--in)]'}`}
    >
      {heavy ? (
        <ShieldAlert size={16} className="mt-0.5 flex-none" />
      ) : (
        <ShieldCheck size={16} className="mt-0.5 flex-none" />
      )}
      <span>
        {heavy
          ? 'حداقل یکی از این حساب‌ها سفارش دارد. تا مطمئن نشده‌اید هر دو حساب مال یک نفر است، ادغام یا رد نکنید؛ در صورت شک با کاربر از طریق تیکت تماس بگیرید.'
          : 'هیچ‌کدام از حساب‌ها سفارشی ندارند؛ ریسک از دست رفتن اطلاعات پایین است. اگر هر دو حساب مال یک نفر نیستند، می‌توانید درخواست را رد کنید.'}
      </span>
    </p>
  );
}

export function ReviewCard({ r, onOpen, onQuick }: { r?: Json; onOpen?: Json; onQuick?: Json }) {
  const [title] = reasonOf(r.reason);
  return (
    // Whole-card click is a pointer shortcut; keyboard users get tabIndex + Enter below.
    // role="button" is not an option because the card contains real buttons.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <article
      className="card card-i stripe rise cursor-pointer p-4 sm:p-5"
      style={{ '--stripe': STRIPE[r.status] || 'var(--ln)' }}
      onClick={() => onOpen(r)}
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onOpen(r)}
      aria-label={`بررسی ${r.email || 'حساب'}`}
    >
      <div className="flex flex-wrap items-center gap-3">
        <ProviderTile p={r.provider} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-extrabold" dir="ltr" style={{ textAlign: 'right' }}>
            {r.email || 'بدون ایمیل'}
          </div>
          <div className="mt-0.5 text-xs text-[var(--mu)]">{title}</div>
        </div>
        <div className="flex items-center gap-2">
          <span className="spec">
            <Clock size={12} />
            {ago(r.created_at)}
          </span>
          <StatusBadge s={r.status} />
        </div>
      </div>
      <div className="mt-4 grid items-center gap-2 md:grid-cols-[1fr_auto_1fr]">
        <UserCard u={r.source_user} role="حساب درخواست‌دهنده" fallbackId={r.source_user_id} />
        <span className="mx-auto grid h-8 w-8 place-items-center rounded-full bg-[var(--mb)] text-[var(--mu)] max-md:rotate-90">
          <ArrowLeftRight size={15} />
        </span>
        <div className="grid gap-2">
          {r.candidates?.length ? (
            r.candidates.slice(0, 2).map((c: Json) => <UserCard key={c.id} u={c} role="حساب موجود" />)
          ) : (
            <UserCard u={null} role="حساب موجود" fallbackId={r.candidate_user_ids?.[0]} />
          )}
          {r.candidates?.length > 2 && (
            <span className="text-center text-[11px] text-[var(--mu)]">+{num(r.candidates.length - 2)} حساب دیگر</span>
          )}
        </div>
      </div>
      {r.status === 'open' && (
        <div
          role="presentation"
          className="mt-4 flex flex-wrap items-center justify-end gap-2"
          onClick={(e) => e.stopPropagation()}
        >
          <button className="btn btn-g" onClick={() => onQuick(r)}>
            رد سریع
          </button>
          <button className="btn !py-1.5 !text-xs" onClick={() => onOpen(r)}>
            <Fingerprint size={14} />
            بررسی و تصمیم
          </button>
        </div>
      )}
      {r.status === 'dismissed' && r.resolution_note && (
        <p className="mt-3 rounded-lg bg-[var(--mb)] p-2.5 text-xs leading-6 text-[var(--mu)]">
          یادداشت ادمین: {r.resolution_note}
        </p>
      )}
    </article>
  );
}
