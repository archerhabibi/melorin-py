import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ReportsView from '../src/ReportsView.jsx';

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
const days = ['2026-10-11', '2026-10-12', '2026-10-13'];
const heat = Array.from({ length: 7 }, () => Array(24).fill(0));
heat[1][21] = 4;
const spark = (v) => ({ value: v, previous: 1, delta_pct: 10, spark: [0, 1, v] });
const payload = (over = {}) => ({
  currency: 'IRT',
  currencies: ['IRT', 'USD'],
  days,
  period: { days: 7, from: days[0], to: days[2], timezone: 'UTC' },
  kpis: {
    revenue: spark(5000),
    orders_sold: spark(3),
    avg_order_value: spark(1666),
    cash_in: spark(4000),
    new_users: spark(2),
    conversion_pct: { value: 75, previous: 60, delta_pct: 25 },
    orders_created: spark(4),
    refunds: { count: 1, amount: 100, previous_count: 0, previous_amount: 0, rate_pct: 25 },
  },
  series: {
    revenue: [0, 2000, 3000],
    revenue_prev: [0, 0, 0],
    orders: [0, 1, 2],
    orders_prev: [0, 0, 0],
    orders_created: [0, 2, 2],
    cash_in: [0, 0, 4000],
    cash_in_count: [0, 0, 1],
    new_users: [0, 1, 1],
    cumulative_revenue: [0, 2000, 5000],
    avg_order_value: [0, 2000, 1500],
  },
  highlights: { best_day: days[2], best_day_revenue: 3000, avg_daily_revenue: 714, wholesale_cost: 0 },
  funnel: { created: 4, paid: 3, completed: 2, failed: 1, cancelled: 0, provisioning_success_pct: 66.7 },
  orders_by_status: [{ status: 'completed', count: 2 }],
  by_method: [{ key: 'wallet', count: 3, revenue: 5000 }],
  by_channel: [{ key: 'telegram', count: 3, revenue: 5000 }],
  by_kind: [{ key: 'purchase', count: 3, revenue: 5000 }],
  top_products: [{ product_id: 'p1', name: 'پلن ماهانه', count: 3, revenue: 5000 }],
  top_stores: [{ store_id: 's1', name: 'فروشگاه اصلی', kind: 'main', count: 3, revenue: 5000, wholesale: 0 }],
  payment_providers: [
    { provider: 'manual_card', succeeded: 2, failed: 0, awaiting_review: 1, amount: 4000, success_rate: 100 },
  ],
  heatmap: { weekday_hour: heat, peak: { weekday: 1, hour: 21, count: 4 }, week_starts: 'monday' },
  attention_orders: 1,
  vpn: { by_status: [], active: 9, expiring_7d: 2, traffic_used_bytes: 1024, traffic_limit_bytes: 4096 },
  tickets: { by_status: [], open: 3 },
  users_total: 40,
  truncated: false,
  ...over,
});

function mockApi(body = payload(), calls = []) {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '');
    calls.push(path);
    if (path.startsWith('/api/v1/admin/stores')) return json([{ id: 's1', name: 'فروشگاه اصلی' }]);
    if (path.startsWith('/api/v1/admin/reports/analytics')) return typeof body === 'function' ? body(path) : json(body);
    return json({}, 404);
  });
  return calls;
}

describe('ReportsView', () => {
  it('renders KPIs, insights, rankings and the heatmap from one analytics payload', async () => {
    const calls = mockApi();
    render(<ReportsView api={{ base: '' }} toast={vi.fn()} />);
    expect(await screen.findByText('پرفروش‌ترین محصولات')).toBeTruthy();
    expect(screen.getByText('پلن ماهانه')).toBeTruthy();
    expect(screen.getAllByText('فروشگاه اصلی').length).toBeGreaterThan(0);
    expect(screen.getByText('یافته‌های کلیدی')).toBeTruthy();
    expect(screen.getByLabelText('سه‌شنبه ساعت ۲۱: ۴ سفارش')).toBeTruthy();
    expect(screen.getByRole('img', { name: /نمودار فروش/ })).toBeTruthy();
    const analytics = calls.find((c) => c.includes('/reports/analytics'));
    expect(analytics).toContain('days=30');
    expect(analytics).toContain('tz=');
  });

  it('refetches when the range or currency changes and keeps money per currency', async () => {
    const calls = mockApi();
    render(<ReportsView api={{ base: '' }} toast={vi.fn()} />);
    await screen.findByText('پرفروش‌ترین محصولات');
    await userEvent.click(screen.getByRole('tab', { name: /۷ روز/ }));
    await waitFor(() => expect(calls.some((c) => c.includes('days=7'))).toBe(true));
    await userEvent.click(await screen.findByRole('tab', { name: 'USD' }));
    await waitFor(() => expect(calls.some((c) => c.includes('currency=USD'))).toBe(true));
  });

  it('offers an accessible table view of the daily numbers', async () => {
    mockApi();
    render(<ReportsView api={{ base: '' }} toast={vi.fn()} />);
    await screen.findByText('پرفروش‌ترین محصولات');
    await userEvent.click(screen.getByRole('button', { name: /جدول/ }));
    const table = await screen.findByRole('table', { name: 'جدول روزانه‌ی گزارش' });
    expect(within(table).getAllByRole('row')).toHaveLength(days.length + 1);
  });

  it('shows an empty-state instead of broken charts when there is no data', async () => {
    mockApi(
      payload({
        top_products: [],
        top_stores: [],
        orders_by_status: [],
        by_method: [],
        by_channel: [],
        by_kind: [],
        payment_providers: [],
        heatmap: { weekday_hour: heat.map((r) => r.map(() => 0)), peak: null, week_starts: 'monday' },
        funnel: { created: 0, paid: 0, completed: 0, failed: 0, cancelled: 0, provisioning_success_pct: 0 },
      }),
    );
    render(<ReportsView api={{ base: '' }} toast={vi.fn()} />);
    expect((await screen.findAllByText('فروشی ثبت نشده')).length).toBeGreaterThan(0);
    expect(screen.getByText('سفارشی در این بازه ثبت نشده.')).toBeTruthy();
  });

  it('reports a failed load without crashing', async () => {
    mockApi((p) => json({ detail: 'x' }, 500));
    render(<ReportsView api={{ base: '' }} toast={vi.fn()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('دریافت گزارش ناموفق بود');
  });
});
