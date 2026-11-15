import { useState } from 'react';
import {
  Bot,
  ChevronLeft,
  CornerDownLeft,
  Keyboard,
  KeyRound,
  MousePointerClick,
  RotateCcw,
  ShieldCheck,
  Terminal,
} from 'lucide-react';
import { Section, Segmented, num, tint } from './kit.tsx';
import { UB_TEXT, parseBot, ubFlows } from './upstreamBot.ts';
import type { Json, Rec } from './types.ts';

export const fmt = (n: Json) => (n > 0 ? num(n) : '—');

// ---------- live preview of what the userbot does ----------
const STEP: Rec = {
  cmd: { Icon: Terminal, tone: 'mu', mono: true },
  btn: { Icon: MousePointerClick, tone: 'in' },
  in: { Icon: Keyboard, tone: 'mu' },
  chk: { Icon: ShieldCheck, tone: 'wn' },
  out: { Icon: CornerDownLeft, tone: 'ok' },
};

export function UpstreamFlowPreview({ ub }: { ub?: Json }) {
  const flows = ubFlows(ub),
    [id, setId] = useState('buy'),
    flow = flows.find((x) => x.id === id) || flows[0];
  return (
    <>
      <Segmented
        label="اقدام"
        value={flow.id}
        onChange={setId}
        options={flows.map((x) => [x.id, x.off ? `${x.title} (خاموش)` : x.title])}
      />
      <ol
        className={`flex flex-wrap items-center gap-y-2 ${flow.off ? 'opacity-45' : ''}`}
        aria-label={`مسیر ${flow.title} در ربات والد`}
      >
        {flow.steps.map((s, i) => {
          const m = STEP[s.k];
          return (
            <li key={i} className="flex items-center">
              <span className="spec" style={tint(m.tone)}>
                <m.Icon size={12} className="shrink-0" />
                <span dir={m.mono ? 'ltr' : 'auto'} className={m.mono ? 'font-mono' : ''}>
                  {s.l}
                </span>
              </span>
              {i < flow.steps.length - 1 && (
                <ChevronLeft size={14} className="mx-1 shrink-0 text-[var(--mu)]" aria-hidden />
              )}
            </li>
          );
        })}
      </ol>
      <p className="text-[11px] leading-5 text-[var(--mu)]">
        هر جریان با <b dir="ltr">{(ub.t.start_command || UB_TEXT.start_command).trim() || UB_TEXT.start_command}</b>{' '}
        شروع می‌شود. دکمه‌های آبی روی منوی خودِ ربات والد زده می‌شوند و نیازی به تایپ دستی ندارند؛ موارد زرد بررسی ایمنی
        قبل از پرداخت‌اند.
      </p>
    </>
  );
}

export function UpstreamFlowSection({ ub }: { ub?: Json }) {
  return (
    <Section
      title="پیش‌نمایش مسیر در ربات والد"
      hint="این همان مسیری است که اکانت تلگرام اختصاصی مثل یک مشتری طی می‌کند؛ با تغییر متن دکمه‌ها زنده به‌روز می‌شود."
    >
      <UpstreamFlowPreview ub={ub} />
    </Section>
  );
}

// ---------- panel card ----------
/** Facts for the panel card header (what this panel is allowed to do). */
export function UpstreamSpecs({ summary }: { summary?: Json }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
      <span className="spec" style={tint('in')}>
        <Bot size={12} />
        <span dir="ltr">@{summary.bot}</span>
      </span>
      <span className="spec" title="سقف مبلغ هر خرید یا تمدید">
        <ShieldCheck size={12} />
        سقف خرید: <b className="num">{fmt(summary.maxPrice)}</b> تومان
      </span>
      <span className="spec" style={tint(summary.renewOn ? 'ok' : 'mu')}>
        <RotateCcw size={12} />
        تمدید {summary.renewOn ? 'فعال' : 'غیرفعال'}
      </span>
      {summary.plans > 0 && (
        <span className="spec">
          <Keyboard size={12} />
          {num(summary.plans)} پلن دستی
        </span>
      )}
      <span className="spec" title="این پنل تعلیق و ازسرگیری ندارد">
        <KeyRound size={12} />
        بدون تعلیق
      </span>
    </div>
  );
}

export { parseBot };
