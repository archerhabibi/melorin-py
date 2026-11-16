import { tint, num } from './kitFormat.ts';
import type { ReactNode } from 'react';
import type { Json } from './types.ts';

/** One cell of a KpiBar. Clickable when `onClick` is given (acts as a filter toggle). */
export function Stat({
  label,
  value,
  tone,
  active,
  onClick,
  Icon,
  sub,
  ring,
}: {
  label?: Json;
  value?: Json;
  tone?: Json;
  active?: Json;
  onClick?: Json;
  Icon?: Json;
  sub?: Json;
  ring?: Json;
}) {
  const body = (
    <>
      {ring != null ? (
        <Ring value={ring} size={46} stroke={5} tone={tone} label={`${label}: ${Math.round(ring * 100)}٪`}>
          <Icon size={16} style={{ color: `var(--${tone})` }} />
        </Ring>
      ) : (
        <span className="tile h-11 w-11" style={tint(tone)}>
          <Icon size={19} />
        </span>
      )}
      <span className="min-w-0">
        {value == null ? (
          <span className="skel block h-6 w-12" role="status" aria-label="در حال بارگذاری" />
        ) : (
          <span className="num block text-2xl font-extrabold leading-none">{num(value)}</span>
        )}
        <span className="mt-1.5 block truncate text-xs text-[var(--mu)]">{label}</span>
        {sub && <span className="mt-0.5 block truncate text-[11px] text-[var(--mu)]">{sub}</span>}
      </span>
    </>
  );
  return onClick ? (
    <button type="button" onClick={onClick} aria-pressed={!!active} className="kpi">
      {body}
    </button>
  ) : (
    <div className="kpi">{body}</div>
  );
}
/** Connected strip of Stat cells (replaces a loose grid of cards). */
export const KpiBar = ({ cols = 4, children }: { cols?: Json; children?: ReactNode }) => (
  <div className="kpis rise" style={{ '--cols': cols }}>
    {children}
  </div>
);

/** Section card. A title like "۲ · اتصال" renders the number as a step badge. */
export function Section({ title, hint, children }: { title?: Json; hint?: Json; children?: ReactNode }) {
  const m = /^([۰-۹0-9]+)\s·\s(.*)$/.exec(title || '');
  return (
    <section className="card space-y-4 p-4 sm:p-5">
      <div>
        <h3 className="flex items-center gap-2 text-[13px] font-extrabold">
          {m ? (
            <>
              <span className="sec-n">{m[1]}</span>
              {m[2]}
            </>
          ) : (
            title
          )}
        </h3>
        {hint && <p className="mt-1.5 text-[11px] leading-5 text-[var(--mu)]">{hint}</p>}
      </div>
      {children}
    </section>
  );
}

/* ---------- v2 visual primitives ---------- */
/** Circular gauge. value 0..1, tone = ok|wn|bd|in|mu. Children render in the centre. */
export function Ring({
  value = 0,
  size = 56,
  stroke = 6,
  tone = 'ok',
  label,
  children,
}: {
  value?: Json;
  size?: Json;
  stroke?: Json;
  tone?: Json;
  label?: Json;
  children?: ReactNode;
}) {
  const r = (size - stroke) / 2,
    c = 2 * Math.PI * r,
    v = Math.max(0, Math.min(1, value || 0));
  return (
    <span
      className="gauge"
      style={{ width: size, height: size }}
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle className="tr" cx={size / 2} cy={size / 2} r={r} strokeWidth={stroke} />
        <circle
          className="fg"
          cx={size / 2}
          cy={size / 2}
          r={r}
          strokeWidth={stroke}
          stroke={`var(--${tone})`}
          strokeDasharray={c}
          strokeDashoffset={c * (1 - v)}
        />
      </svg>
      <span className="relative grid place-items-center text-center leading-none">{children}</span>
    </span>
  );
}
/** Segmented capacity meter (value 0..1). */
export function SegMeter({
  value = 0,
  tone = 'ok',
  label,
  max,
  now,
}: {
  value?: Json;
  tone?: Json;
  label?: Json;
  max?: Json;
  now?: Json;
}) {
  const v = Math.max(0, Math.min(1, value || 0));
  return (
    <div className="seg" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={max} aria-valuenow={now}>
      <i style={{ width: `${v * 100}%`, background: `var(--${tone})` }} />
    </div>
  );
}
/** Thin continuous bar. */
export const Bar = ({ value = 0, tone = 'ok', label }: { value?: Json; tone?: Json; label?: Json }) => (
  <div className="bar" role="progressbar" aria-label={label} aria-valuenow={Math.round(value * 100)}>
    <i style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%`, background: `var(--${tone})` }} />
  </div>
);
