import type { ReactNode } from 'react';
import { useState } from 'react';
import { AlertTriangle, ChevronDown, Terminal } from 'lucide-react';
import { CopyButton } from '../../shared/kit.tsx';
import type { Json } from '../../shared/types.ts';

export function Step({ n, children }: { n?: Json; children?: ReactNode }) {
  return (
    <li className="flex items-start gap-2.5">
      <span className="sec-n mt-0.5 shrink-0">{n}</span>
      <span className="min-w-0 flex-1 leading-6">{children}</span>
    </li>
  );
}
export function Cmd({ text }: { text?: Json }) {
  return (
    <span className="mt-1 flex items-center gap-1.5">
      <code
        dir="ltr"
        className="min-w-0 flex-1 break-all rounded-lg bg-[var(--sf2)] px-2.5 py-1.5 font-mono text-[11px]"
        title={text}
      >
        {text}
      </code>
      <CopyButton text={text} label="کپی دستور" />
    </span>
  );
}

export function UpstreamGuide() {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-xl border border-[var(--hair)] bg-[var(--sf2)]">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-xs font-bold"
      >
        <Terminal size={14} className="text-[var(--in)]" />
        راهنمای گرفتن api_id، api_hash و session
        <ChevronDown size={14} className={`mr-auto text-[var(--mu)] ${open ? '' : '-rotate-90'}`} />
      </button>
      {open && (
        <ol className="space-y-3 border-t border-[var(--hair)] px-3 py-3 text-xs">
          <Step n="۱">
            یک اکانت تلگرام <b>جداگانه</b> بسازید (نه شماره‌ی شخصی) و از همان اکانت، کیف پول ربات والد را شارژ کنید.
          </Step>
          <Step n="۲">
            در{' '}
            <a
              className="font-bold text-[var(--ac)] underline"
              dir="ltr"
              href="https://my.telegram.org/apps"
              target="_blank"
              rel="noopener noreferrer"
            >
              my.telegram.org/apps
            </a>{' '}
            با همان شماره وارد شوید و یک اپلیکیشن بسازید؛ <b>api_id</b> و <b>api_hash</b> همان‌جا نمایش داده می‌شود.
          </Step>
          <Step n="۳">
            روی سروری که کد پروژه دارد، اسکریپت ورود را اجرا کنید؛ شماره، کد تلگرام و (در صورت وجود) رمز دومرحله‌ای را
            می‌پرسد:
            <Cmd text="pip install telethon" />
            <Cmd text="python scripts/upstream_bot_login.py" />
          </Step>
          <Step n="۴">
            خروجی آخر اسکریپت (رشته‌ی طولانی <b>StringSession</b>) را در فیلد «Session» بچسبانید.
          </Step>
          <li className="flex items-start gap-2 rounded-lg bg-[var(--wnb)] p-2.5 leading-6 text-[var(--wn)]">
            <AlertTriangle size={14} className="mt-1 shrink-0" />
            Session دسترسی کامل به آن اکانت تلگرام است؛ مثل رمز عبور نگه دارید و جایی منتشر نکنید. اگر لو رفت، از
            تنظیمات تلگرام (Devices) نشست را ببندید و دوباره بگیرید.
          </li>
        </ol>
      )}
    </div>
  );
}

/** The three secrets, shown only while they are being (re)entered. All three are required together: the API replaces the whole secret. */
