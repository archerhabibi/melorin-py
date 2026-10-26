import { describe, expect, it } from 'vitest';
import {
  buildInsights,
  buildQuery,
  dailyRows,
  deltaInfo,
  donutSegments,
  foldTail,
  fmtBytes,
  heatLevel,
  share,
  WEEK_ORDER,
} from '../src/reportsLogic.js';

const base = () => ({
  currency: 'IRT',
  days: ['2026-10-12', '2026-10-13'],
  kpis: {
    revenue: { value: 5000, previous: 2000, delta_pct: 150 },
    conversion_pct: { value: 80, previous: 70, delta_pct: 14.3 },
    refunds: { count: 0, rate_pct: 0 },
  },
  series: { revenue: [1, 2], orders: [1, 1], cash_in: [0, 5], new_users: [2, 3] },
  highlights: { best_day: '2026-10-13', best_day_revenue: 3000 },
  heatmap: { peak: { weekday: 1, hour: 21, count: 4 } },
  funnel: { created: 20 },
  top_stores: [],
  payment_providers: [],
  vpn: { expiring_7d: 0 },
  attention_orders: 0,
  truncated: false,
});

describe('reportsLogic', () => {
  it('describes deltas and flips good/bad for inverted metrics', () => {
    expect(deltaInfo(null).dir).toBe('none');
    expect(deltaInfo(0.01).dir).toBe('flat');
    expect(deltaInfo(12)).toMatchObject({ dir: 'up', good: true });
    expect(deltaInfo(12, { invert: true })).toMatchObject({ dir: 'up', good: false });
    expect(deltaInfo(-5)).toMatchObject({ dir: 'down', good: false });
  });

  it('builds donut segments that add up to the full ring and skip empty items', () => {
    const segs = donutSegments([
      { key: 'a', value: 3 },
      { key: 'b', value: 0 },
      { key: 'c', value: 1 },
    ]);
    expect(segs.map((s) => s.key)).toEqual(['a', 'c']);
    expect(segs[0].pct + segs[1].pct).toBeCloseTo(100);
    expect(segs[1].offset).toBeCloseTo(-75);
    expect(donutSegments([{ key: 'a', value: 0 }])).toEqual([]);
  });

  it('draws a lone positive segment as a full ring even when other rows are zero', () => {
    const [seg] = donutSegments([
      { key: 'a', value: 7 },
      { key: 'b', value: 0 },
    ]);
    expect(seg.dash).toBeCloseTo(100);
  });

  it('folds a long tail into one "other" row and keeps the total', () => {
    const rows = Array.from({ length: 8 }, (_, i) => ({ key: `k${i}`, label: `k${i}`, value: 10 }));
    const out = foldTail(rows, 5);
    expect(out).toHaveLength(5);
    expect(out[4]).toMatchObject({ key: '__other', value: 40 });
    expect(foldTail(rows.slice(0, 3), 5)).toHaveLength(3);
  });

  it('scales heat cells with a visible floor and handles an empty matrix', () => {
    expect(heatLevel(0, 10)).toBe(0);
    expect(heatLevel(1, 100)).toBeGreaterThanOrEqual(0.12);
    expect(heatLevel(100, 100)).toBe(1);
    expect(heatLevel(5, 0)).toBe(0);
  });

  it('orders the Persian week from Saturday and formats sizes and shares', () => {
    expect(WEEK_ORDER).toEqual([5, 6, 0, 1, 2, 3, 4]);
    expect(share(1, 4)).toBe(25);
    expect(share(1, 0)).toBe(0);
    expect(fmtBytes(0)).toContain('B');
    expect(fmtBytes(5 * 1024 ** 3)).toContain('GB');
  });

  it('turns the payload into ranked, plain-language insights', () => {
    const d = base();
    d.top_stores = [
      { name: 'فروشگاه الف', revenue: 4000 },
      { name: 'ب', revenue: 1000 },
    ];
    d.attention_orders = 3;
    d.vpn.expiring_7d = 2;
    d.payment_providers = [{ provider: 'zarinpal', succeeded: 2, failed: 8, success_rate: 20 }];
    d.truncated = true;
    const ids = buildInsights(d).map((i) => i.id);
    expect(ids).toEqual(
      expect.arrayContaining([
        'revenue-delta',
        'best-day',
        'peak-hour',
        'concentration',
        'attention',
        'expiring',
        'provider-zarinpal',
        'truncated',
      ]),
    );
    expect(buildInsights(d).find((i) => i.id === 'attention').tone).toBe('bd');
    expect(buildInsights(null)).toEqual([]);
  });

  it('stays quiet when there is nothing notable', () => {
    const d = base();
    d.kpis.revenue = { value: 0, previous: 0, delta_pct: null };
    d.highlights = { best_day: null, best_day_revenue: 0 };
    d.heatmap = { peak: null };
    expect(buildInsights(d)).toEqual([]);
  });

  it('flags low conversion only with enough orders', () => {
    const d = base();
    d.kpis.conversion_pct.value = 30;
    expect(buildInsights(d).some((i) => i.id === 'conversion')).toBe(true);
    d.funnel.created = 3;
    expect(buildInsights(d).some((i) => i.id === 'conversion')).toBe(false);
  });

  it('builds the table rows and the query string', () => {
    expect(dailyRows(base())).toEqual([
      { day: '2026-10-12', revenue: 1, orders: 1, cash_in: 0, new_users: 2 },
      { day: '2026-10-13', revenue: 2, orders: 1, cash_in: 5, new_users: 3 },
    ]);
    expect(buildQuery({ days: 30, tz: 'Asia/Tehran', currency: '', storeId: '' })).toBe('days=30&tz=Asia%2FTehran');
    expect(buildQuery({ days: 7, tz: 'UTC', currency: 'USD', storeId: 'abc' })).toBe(
      'days=7&tz=UTC&currency=USD&store_id=abc',
    );
  });
});
