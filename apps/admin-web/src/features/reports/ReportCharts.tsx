import type { Json } from '../../shared/types.ts';

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

export function Legend({ items }: { items?: Json }) {
  if (items.length < 2) return null;
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--mu)]" aria-label="راهنمای نمودار">
      {items.map((it: Json) => (
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
export function Sparkline({
  values,
  color = 'var(--rc1)',
  w = 96,
  h = 30,
}: {
  values?: Json;
  color?: Json;
  w?: Json;
  h?: Json;
}) {
  if (!values) return null;
  if (!values.length || !values.some(Boolean))
    return <div aria-hidden="true" className="h-[30px] w-24 rounded bg-[var(--mb)] opacity-60" />;
  const max = Math.max(...values, 1);
  const pts = values.map((v: Json, i: Json) => [
    (i * (w - 4)) / Math.max(1, values.length - 1) + 2,
    h - 3 - (v / max) * (h - 8),
  ]);
  const d = pts.map(([x, y]: Json, i: Json) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const [lx, ly] = pts[pts.length - 1];
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width={w} height={h} aria-hidden="true" {...{ dir: 'ltr' }}>
      <path d={d} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={lx} cy={ly} r="3" fill="var(--sf)" stroke={color} strokeWidth="2" />
    </svg>
  );
}
