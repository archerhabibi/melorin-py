import { useState } from 'react';

const compact = new Intl.NumberFormat('fa-IR', { notation: 'compact', maximumFractionDigits: 1 });
const full = new Intl.NumberFormat('fa-IR');
export const dayShort = (iso) =>
  new Intl.DateTimeFormat('fa-IR-u-ca-persian', { day: 'numeric', month: 'short' }).format(
    new Date(`${iso}T12:00:00Z`),
  );
export const dayLong = (iso) =>
  new Intl.DateTimeFormat('fa-IR-u-ca-persian', { weekday: 'long', day: 'numeric', month: 'long' }).format(
    new Date(`${iso}T12:00:00Z`),
  );

// Dependency-free responsive SVG chart: smooth area or bars, hover/touch tooltip, themed via CSS variables.
export function TrendChart({ days, values, color = 'var(--ac)', bars = false, unit = '', label, h = 230 }) {
  const [hi, setHi] = useState(null);
  const W = 720,
    P = { l: 50, r: 10, t: 14, b: 28 },
    n = values.length;
  const max = Math.max(...values, 1),
    iw = W - P.l - P.r,
    ih = h - P.t - P.b;
  const x = (i) => P.l + (n > 1 ? (i * iw) / (n - 1) : iw / 2);
  const y = (v) => P.t + ih * (1 - v / max);
  const pts = values.map((v, i) => [x(i), y(v)]);
  const line = pts.map(([a, b], i) => `${i ? 'L' : 'M'}${a.toFixed(1)},${b.toFixed(1)}`).join(' ');
  const area = `${line} L${x(n - 1).toFixed(1)},${y(0)} L${x(0).toFixed(1)},${y(0)} Z`;
  const ticks = Array.from(new Set([0, 1, 2, 3, 4].map((k) => Math.round((k * (n - 1)) / 4))));
  const bw = Math.max(2, Math.min(22, (iw / n) * 0.62));
  const move = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    setHi(Math.max(0, Math.min(n - 1, Math.round(((px - P.l) / iw) * (n - 1)))));
  };
  const gid = `g${color.replace(/\W/g, '')}`;
  return (
    <div className="relative" dir="ltr">
      <svg
        viewBox={`0 0 ${W} ${h}`}
        className="w-full touch-pan-y"
        role="img"
        aria-label={label}
        onPointerMove={move}
        onPointerLeave={() => setHi(null)}
      >
        <defs>
          <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity=".28" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
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
              {compact.format(Math.round(max * f))}
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
        {bars ? (
          values.map((v, i) => (
            <rect
              key={i}
              x={x(i) - bw / 2}
              y={y(v)}
              width={bw}
              height={Math.max(0, y(0) - y(v))}
              rx="3"
              fill={color}
              opacity={hi === null || hi === i ? 0.9 : 0.35}
            />
          ))
        ) : (
          <>
            <path d={area} fill={`url(#${gid})`} />
            <path d={line} fill="none" stroke={color} strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" />
          </>
        )}
        {hi !== null && (
          <g>
            <line x1={x(hi)} x2={x(hi)} y1={P.t} y2={y(0)} stroke="var(--mu)" strokeDasharray="3 4" />
            {!bars && <circle cx={x(hi)} cy={y(values[hi])} r="5" fill="var(--sf)" stroke={color} strokeWidth="2.5" />}
          </g>
        )}
      </svg>
      {hi !== null && (
        <div
          className="pointer-events-none absolute top-0 z-10 -translate-x-1/2 rounded-lg bg-[var(--nav)] px-3 py-2 text-xs text-white shadow-lg"
          dir="rtl"
          style={{ left: `${Math.min(86, Math.max(14, (x(hi) / W) * 100))}%` }}
        >
          <div className="text-white/70">{dayLong(days[hi])}</div>
          <div className="mt-0.5 font-bold">
            {full.format(values[hi])} {unit}
          </div>
        </div>
      )}
    </div>
  );
}
