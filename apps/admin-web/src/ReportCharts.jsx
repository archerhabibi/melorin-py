// Dependency-free SVG/HTML chart primitives for the Reports screen. Colors come from --rc1..--rc8 (see styles.css),
// text always wears text tokens (never the series color), every chart has an aria-label and a keyboard path.
import { useId, useState } from 'react';
import { dayLong, dayShort } from './charts.jsx';
import { WEEKDAY_FA, WEEK_ORDER, donutSegments, fmt, fmtCompact, fmtPct, heatLevel, nf } from './reportsLogic.js';

export const SERIES_COLORS = [
  'var(--rc1)',
  'var(--rc2)',
  'var(--rc3)',
  'var(--rc4)',
  'var(--rc5)',
  'var(--rc6)',
  'var(--rc7)',
  'var(--rc8)',
];

export function Legend({ items }) {
  if (items.length < 2) return null;
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--mu)]" aria-label="راهنمای نمودار">
      {items.map((it) => (
        <li key={it.key} className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="inline-block h-0 w-4 border-t-2"
            style={{ borderColor: it.color, borderTopStyle: it.dashed ? 'dashed' : 'solid' }}
          />
          <span className="text-[var(--tx)]">{it.label}</span>
        </li>
      ))}
    </ul>
  );
}

/** Tiny trend line for KPI cards (decorative: the number beside it carries the value). */
export function Sparkline({ values, color = 'var(--rc1)', w = 96, h = 30 }) {
  if (!values) return null;
  if (!values.length || !values.some(Boolean))
    return <div aria-hidden="true" className="h-[30px] w-24 rounded bg-[var(--mb)] opacity-60" />;
  const max = Math.max(...values, 1);
  const pts = values.map((v, i) => [(i * (w - 4)) / Math.max(1, values.length - 1) + 2, h - 3 - (v / max) * (h - 8)]);
  const d = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const [lx, ly] = pts[pts.length - 1];
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width={w} height={h} aria-hidden="true" dir="ltr">
      <path d={d} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={lx} cy={ly} r="3" fill="var(--sf)" stroke={color} strokeWidth="2" />
    </svg>
  );
}

/**
 * Multi-series line/area chart over a day axis with crosshair tooltip (pointer + arrow keys).
 * series: [{ key, label, values, color, dashed?, area? }]
 */
export function CompareChart({ days, series, unit = '', label, h = 260, bars = false }) {
  const [hi, setHi] = useState(null);
  const gid = useId().replace(/:/g, '');
  const W = 760;
  const P = { l: 54, r: 12, t: 14, b: 28 };
  const n = days.length;
  const max = Math.max(1, ...series.flatMap((s) => s.values));
  const iw = W - P.l - P.r;
  const ih = h - P.t - P.b;
  const x = (i) => P.l + (n > 1 ? (i * iw) / (n - 1) : iw / 2);
  const y = (v) => P.t + ih * (1 - v / max);
  const path = (vals) => vals.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const ticks = Array.from(new Set([0, 1, 2, 3, 4].map((k) => Math.round((k * (n - 1)) / 4))));
  const bw = Math.max(2, Math.min(20, (iw / n) * 0.6));
  const move = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    setHi(Math.max(0, Math.min(n - 1, Math.round(((px - P.l) / iw) * (n - 1)))));
  };
  const key = (e) => {
    if (e.key === 'ArrowLeft') setHi((v) => Math.min(n - 1, (v ?? -1) + 1));
    else if (e.key === 'ArrowRight') setHi((v) => Math.max(0, (v ?? n) - 1));
    else if (e.key === 'Escape') setHi(null);
    else return;
    e.preventDefault();
  };
  return (
    <div className="relative" dir="ltr">
      <svg
        viewBox={`0 0 ${W} ${h}`}
        className="w-full touch-pan-y"
        role="img"
        tabIndex={0}
        aria-label={`${label}. با کلیدهای جهت‌نما روزها را مرور کنید.`}
        onPointerMove={move}
        onPointerLeave={() => setHi(null)}
        onKeyDown={key}
        onBlur={() => setHi(null)}
      >
        <defs>
          {series.map((s) => (
            <linearGradient key={s.key} id={`${gid}${s.key}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={s.color} stopOpacity=".22" />
              <stop offset="100%" stopColor={s.color} stopOpacity="0" />
            </linearGradient>
          ))}
        </defs>
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line
              x1={P.l}
              x2={W - P.r}
              y1={y(max * f)}
              y2={y(max * f)}
              stroke="var(--ln)"
              strokeDasharray={f ? '3 5' : ''}
            />
            <text x={P.l - 8} y={y(max * f) + 4} textAnchor="end" fontSize="11" fill="var(--mu)">
              {fmtCompact(max * f)}
            </text>
          </g>
        ))}
        {ticks.map((i) => (
          <text
            key={i}
            x={x(i)}
            y={h - 8}
            textAnchor={i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'}
            fontSize="11"
            fill="var(--mu)"
          >
            {dayShort(days[i])}
          </text>
        ))}
        {bars
          ? series
              .slice(0, 1)
              .map((s) =>
                s.values.map((v, i) => (
                  <rect
                    key={i}
                    x={x(i) - bw / 2}
                    y={y(v)}
                    width={bw}
                    height={Math.max(0, y(0) - y(v))}
                    rx="3"
                    fill={s.color}
                    opacity={hi === null || hi === i ? 0.95 : 0.4}
                  />
                )),
              )
          : series.map((s) => (
              <g key={s.key}>
                {s.area && (
                  <path d={`${path(s.values)} L${x(n - 1)},${y(0)} L${x(0)},${y(0)} Z`} fill={`url(#${gid}${s.key})`} />
                )}
                <path
                  d={path(s.values)}
                  fill="none"
                  stroke={s.color}
                  strokeWidth={s.dashed ? 1.8 : 2.4}
                  strokeDasharray={s.dashed ? '5 4' : undefined}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
              </g>
            ))}
        {hi !== null && (
          <g>
            <line x1={x(hi)} x2={x(hi)} y1={P.t} y2={y(0)} stroke="var(--mu)" strokeDasharray="3 4" />
            {!bars &&
              series.map((s) => (
                <circle
                  key={s.key}
                  cx={x(hi)}
                  cy={y(s.values[hi])}
                  r="5"
                  fill="var(--sf)"
                  stroke={s.color}
                  strokeWidth="2.5"
                />
              ))}
          </g>
        )}
      </svg>
      {hi !== null && (
        <div
          role="status"
          className="pointer-events-none absolute top-0 z-10 min-w-[9rem] -translate-x-1/2 rounded-lg bg-[var(--nav)] px-3 py-2 text-xs text-white shadow-lg"
          dir="rtl"
          style={{ left: `${Math.min(84, Math.max(16, (x(hi) / W) * 100))}%` }}
        >
          <div className="text-white/70">{dayLong(days[hi])}</div>
          {series.map((s) => (
            <div key={s.key} className="mt-1 flex items-center justify-between gap-3">
              <span className="flex items-center gap-1.5 text-white/80">
                <span
                  aria-hidden="true"
                  className="inline-block h-2 w-2 rounded-full"
                  style={{ background: s.color }}
                />
                {s.label}
              </span>
              <b>
                {fmt(s.values[hi])} {unit}
              </b>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Donut with center total. items: [{ key, label, value, color }]. Always paired with a legend list (values in text). */
export function Donut({ items, center, sub, label, size = 150, stack = false }) {
  const segs = donutSegments(items);
  const [on, setOn] = useState(null);
  const total = items.reduce((a, x) => a + x.value, 0);
  return (
    <div className={stack ? 'flex flex-col items-center gap-4' : 'flex flex-wrap items-center gap-5'}>
      <div className="relative shrink-0" style={{ width: size, height: size }}>
        <svg viewBox="0 0 36 36" width={size} height={size} role="img" aria-label={label} className="-rotate-90">
          <circle cx="18" cy="18" r="15.9155" fill="none" stroke="var(--mb)" strokeWidth="4.2" />
          {segs.map((s) => (
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
              {on ? fmtPct((items.find((x) => x.key === on)?.value / (total || 1)) * 100) : center}
            </div>
            <div className="text-[10px] text-[var(--mu)]">{on ? items.find((x) => x.key === on)?.label : sub}</div>
          </div>
        </div>
      </div>
      <ul className={`space-y-1.5 text-sm ${stack ? 'w-full' : 'min-w-[9rem] flex-1'}`}>
        {items.map((it) => (
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
export function HBars({ rows, color = 'var(--rc1)', empty = 'داده‌ای برای نمایش نیست' }) {
  if (!rows.length) return <p className="py-6 text-center text-sm text-[var(--mu)]">{empty}</p>;
  const max = Math.max(...rows.map((r) => r.value), 1);
  return (
    <ol className="space-y-3">
      {rows.map((r, i) => (
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
export function Heatmap({ matrix, peak }) {
  const [tip, setTip] = useState(null);
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
export function Funnel({ stages }) {
  const top = Math.max(stages[0]?.value || 0, 1);
  const tint = [55, 75, 95];
  return (
    <ol className="space-y-2.5">
      {stages.map((s, i) => {
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
