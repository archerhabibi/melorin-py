import { useId, useState } from 'react';
import { dayLong, dayShort } from '../../shared/charts.tsx';
import { fmt, fmtCompact } from './reportsLogic.ts';
import type { Json } from '../../shared/types.ts';
import { Donut } from './DistributionCharts';

/**
 * Multi-series line/area chart over a day axis with crosshair tooltip (pointer + arrow keys).
 * series: [{ key, label, values, color, dashed?, area? }]
 */
export function CompareChart({
  days,
  series,
  unit = '',
  label,
  h = 260,
  bars = false,
}: {
  days?: Json;
  series?: Json;
  unit?: Json;
  label?: Json;
  h?: Json;
  bars?: Json;
}) {
  const [hi, setHi] = useState<Json>(null);
  const gid = useId().replace(/:/g, '');
  const W = 760;
  const P = { l: 54, r: 12, t: 14, b: 28 };
  const n = days.length;
  const max = Math.max(1, ...series.flatMap((s: Json) => s.values));
  const iw = W - P.l - P.r;
  const ih = h - P.t - P.b;
  const x = (i: Json) => P.l + (n > 1 ? (i * iw) / (n - 1) : iw / 2);
  const y = (v: Json) => P.t + ih * (1 - v / max);
  const path = (vals: Json) =>
    vals.map((v: Json, i: Json) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const ticks = Array.from(new Set([0, 1, 2, 3, 4].map((k) => Math.round((k * (n - 1)) / 4))));
  const bw = Math.max(2, Math.min(20, (iw / n) * 0.6));
  const move = (e: Json) => {
    const r = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    setHi(Math.max(0, Math.min(n - 1, Math.round(((px - P.l) / iw) * (n - 1)))));
  };
  const key = (e: Json) => {
    if (e.key === 'ArrowLeft') setHi((v: Json) => Math.min(n - 1, (v ?? -1) + 1));
    else if (e.key === 'ArrowRight') setHi((v: Json) => Math.max(0, (v ?? n) - 1));
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
          {series.map((s: Json) => (
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
              .map((s: Json) =>
                s.values.map((v: Json, i: Json) => (
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
          : series.map((s: Json) => (
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
              series.map((s: Json) => (
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
          {series.map((s: Json) => (
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
