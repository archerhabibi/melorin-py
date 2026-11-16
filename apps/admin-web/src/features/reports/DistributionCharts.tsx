import { useState } from 'react';
import { WEEKDAY_FA, WEEK_ORDER, donutSegments, fmt, fmtPct, heatLevel, nf } from './reportsLogic.ts';
import type { Json } from '../../shared/types.ts';

/** Donut with center total. items: [{ key, label, value, color }]. Always paired with a legend list (values in text). */
export function Donut({
  items,
  center,
  sub,
  label,
  size = 150,
  stack = false,
}: {
  items?: Json;
  center?: Json;
  sub?: Json;
  label?: Json;
  size?: Json;
  stack?: Json;
}) {
  const segs = donutSegments(items);
  const [on, setOn] = useState<Json>(null);
  const total = items.reduce((a: Json, x: Json) => a + x.value, 0);
  return (
    <div className={stack ? 'flex flex-col items-center gap-4' : 'flex flex-wrap items-center gap-5'}>
      <div className="relative shrink-0" style={{ width: size, height: size }}>
        <svg viewBox="0 0 36 36" width={size} height={size} role="img" aria-label={label} className="-rotate-90">
          <circle cx="18" cy="18" r="15.9155" fill="none" stroke="var(--mb)" strokeWidth="4.2" />
          {segs.map((s: Json) => (
            <circle
              key={s.key}
              cx="18"
              cy="18"
              r="15.9155"
              fill="none"
              stroke={s.color}
              strokeWidth={on === s.key ? 5.2 : 4.2}
              strokeDasharray={`${s.dash} ${100 - s.dash}`}
              strokeDashoffset={s.offset}
              onPointerEnter={() => setOn(s.key)}
              onPointerLeave={() => setOn(null)}
            >
              <title>{`${s.label}: ${fmt(s.value)}`}</title>
            </circle>
          ))}
        </svg>
        <div className="pointer-events-none absolute inset-0 grid place-items-center text-center">
          <div>
            <div className="text-lg font-extrabold leading-tight">
              {on ? fmtPct((items.find((x: Json) => x.key === on)?.value / (total || 1)) * 100) : center}
            </div>
            <div className="text-[10px] text-[var(--mu)]">
              {on ? items.find((x: Json) => x.key === on)?.label : sub}
            </div>
          </div>
        </div>
      </div>
      <ul className={`space-y-1.5 text-sm ${stack ? 'w-full' : 'min-w-[9rem] flex-1'}`}>
        {items.map((it: Json) => (
          <li
            key={it.key}
            className="flex items-center justify-between gap-3 rounded-md px-1.5 py-0.5"
            onPointerEnter={() => setOn(it.key)}
            onPointerLeave={() => setOn(null)}
          >
            <span className="flex items-center gap-2">
              <span
                aria-hidden="true"
                className="inline-block h-2.5 w-2.5 rounded-sm"
                style={{ background: it.color }}
              />
              {it.label}
            </span>
            <span className="text-xs text-[var(--mu)]">
              <b className="text-[var(--tx)]">{fmt(it.value)}</b> · {fmtPct((it.value / (total || 1)) * 100)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Horizontal ranking bars. rows: [{ key, label, sub, value, display }]; all bars share one color (magnitude, not identity). */
export function HBars({
  rows,
  color = 'var(--rc1)',
  empty = 'داده‌ای برای نمایش نیست',
}: {
  rows?: Json;
  color?: Json;
  empty?: Json;
}) {
  if (!rows.length) return <p className="py-6 text-center text-sm text-[var(--mu)]">{empty}</p>;
  const max = Math.max(...rows.map((r: Json) => r.value), 1);
  return (
    <ol className="space-y-3">
      {rows.map((r: Json, i: Json) => (
        <li key={r.key} title={r.label}>
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="flex min-w-0 items-baseline gap-2">
              <span className="text-xs text-[var(--mu)]">{nf.format(i + 1)}</span>
              <span className="truncate font-bold">{r.label}</span>
              {r.sub && <span className="shrink-0 text-xs text-[var(--mu)]">{r.sub}</span>}
            </span>
            <span className="shrink-0 text-xs font-bold">{r.display}</span>
          </div>
          <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-[var(--mb)]" role="presentation">
            <div
              className="h-full rounded-full"
              style={{ width: `${Math.max(2, (r.value / max) * 100)}%`, background: color }}
            />
          </div>
        </li>
      ))}
    </ol>
  );
}

/** Weekday x hour heatmap of sold orders (sequential single hue, sqrt intensity). */
export function Heatmap({ matrix, peak }: { matrix?: Json; peak?: Json }) {
  const [tip, setTip] = useState<Json>(null);
  const max = Math.max(0, ...matrix.flat());
  const hours = Array.from({ length: 24 }, (_, h) => h);
  return (
    <div>
      <div className="overflow-x-auto pb-1" dir="ltr">
        <div className="min-w-[560px]">
          <div className="grid gap-[3px]" style={{ gridTemplateColumns: '64px repeat(24, minmax(0, 1fr))' }}>
            <span />
            {hours.map((h) => (
              <span key={h} className="text-center text-[10px] text-[var(--mu)]">
                {h % 3 === 0 ? nf.format(h) : ''}
              </span>
            ))}
            {WEEK_ORDER.map((wd) => (
              <div key={wd} className="contents">
                <span className="self-center pr-2 text-right text-xs text-[var(--mu)]" dir="rtl">
                  {WEEKDAY_FA[wd]}
                </span>
                {hours.map((h) => {
                  const c = matrix[wd][h];
                  const lv = heatLevel(c, max);
                  return (
                    <button
                      key={h}
                      type="button"
                      className="rcell aspect-square w-full rounded-[4px] border-0 p-0"
                      aria-label={`${WEEKDAY_FA[wd]} ساعت ${nf.format(h)}: ${fmt(c)} سفارش`}
                      style={{
                        background: lv
                          ? `color-mix(in srgb, var(--rseq) ${Math.round(lv * 100)}%, var(--sf))`
                          : 'var(--mb)',
                      }}
                      onPointerEnter={() => setTip({ wd, h, c })}
                      onFocus={() => setTip({ wd, h, c })}
                      onPointerLeave={() => setTip(null)}
                      onBlur={() => setTip(null)}
                    />
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      </div>
      <div
        className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-[var(--mu)]"
        aria-live="polite"
      >
        <span>
          {tip
            ? `${WEEKDAY_FA[tip.wd]}، ساعت ${nf.format(tip.h)}: ${fmt(tip.c)} سفارش`
            : peak
              ? `اوج: ${WEEKDAY_FA[peak.weekday]} ساعت ${nf.format(peak.hour)} (${fmt(peak.count)} سفارش)`
              : 'هنوز سفارشی در این بازه نیست'}
        </span>
        <span className="flex items-center gap-1.5" aria-hidden="true">
          کم
          {[0.15, 0.4, 0.7, 1].map((v) => (
            <i
              key={v}
              className="inline-block h-3 w-4 rounded-sm"
              style={{ background: `color-mix(in srgb, var(--rseq) ${v * 100}%, var(--sf))` }}
            />
          ))}
          زیاد
        </span>
      </div>
    </div>
  );
}

/** Ordered funnel (ordinal single-hue ramp, light -> dark). stages: [{ key, label, value }]. */
export function Funnel({ stages }: { stages?: Json }) {
  const top = Math.max(stages[0]?.value || 0, 1);
  const tint = [55, 75, 95];
  return (
    <ol className="space-y-2.5">
      {stages.map((s: Json, i: Json) => {
        const prev = i ? stages[i - 1].value : null;
        return (
          <li key={s.key}>
            <div className="flex items-baseline justify-between text-sm">
              <span className="font-bold">{s.label}</span>
              <span className="text-xs text-[var(--mu)]">
                <b className="text-[var(--tx)]">{fmt(s.value)}</b>
                {prev ? ` · ${fmtPct((s.value / (prev || 1)) * 100)} از مرحله قبل` : ''}
              </span>
            </div>
            <div className="mt-1 h-7 overflow-hidden rounded-md bg-[var(--mb)]" role="presentation">
              <div
                className="h-full rounded-md"
                style={{
                  width: `${Math.max(1.5, (s.value / top) * 100)}%`,
                  background: `color-mix(in srgb, var(--rseq) ${tint[i % 3]}%, var(--sf))`,
                }}
              />
            </div>
          </li>
        );
      })}
    </ol>
  );
}
