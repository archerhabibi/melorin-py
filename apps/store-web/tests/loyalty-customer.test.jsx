import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Loyalty from '../src/Loyalty.tsx';
import { multiplierLabel, tierProgress } from '../src/loyaltyFormat.ts';

const res = (body, status = 200) => new Response(JSON.stringify(body), { status });

const club = (over = {}) => ({
  store_id: 's1',
  enabled: true,
  currency: 'IRT',
  balance: 700,
  lifetime_earned: 900,
  debt: 0,
  tier: { name: 'نقره‌ای', min_points: 500, multiplier_bp: 11000 },
  next_tier: { name: 'طلایی', min_points: 2000, points_missing: 1100 },
  tiers: [],
  program: { enabled: true, first_order_bonus: 0 },
  rewards: [
    {
      id: 'r1',
      name: 'اعتبار ۵ هزار',
      cost_points: 500,
      value: 5000,
      remaining: null,
      available: true,
      blocked_reason: null,
    },
    {
      id: 'r2',
      name: 'اعتبار ۵۰ هزار',
      cost_points: 5000,
      value: 50000,
      remaining: 3,
      available: false,
      blocked_reason: 'LOYALTY_NOT_ENOUGH_POINTS',
    },
  ],
  history: [{ id: 't1', kind: 'order_earn', amount: 120, created_at: '2026-11-01T10:00:00Z' }],
  history_more: false,
  ...over,
});

describe('loyalty helpers', () => {
  it('shows the multiplier from basis points', () => {
    expect(multiplierLabel(12500)).toBe('۱٫۲۵×');
  });
  it('measures progress between the current and the next tier, full at the top', () => {
    expect(tierProgress({ min_points: 500 }, { min_points: 2000 }, 1250)).toBe(50);
    expect(tierProgress({ min_points: 5000 }, null, 9000)).toBe(100);
    expect(tierProgress(null, { min_points: 500 }, 0)).toBe(0);
  });
});

describe('customer loyalty card (this store only)', () => {
  it('asks Core for the club of the store it is in and shows points, tier and what is blocked', async () => {
    const calls = [];
    const coreFetch = vi.fn(async (path) => {
      calls.push(path);
      return res(club());
    });
    render(<Loyalty coreFetch={coreFetch} storeId="s1" notify={vi.fn()} />);
    expect(await screen.findByTestId('loyalty-balance')).toHaveTextContent('۷۰۰');
    expect(calls).toEqual(['/api/v1/stores/s1/loyalty']);
    expect(screen.getByText('نقره‌ای')).toBeInTheDocument();
    expect(screen.getByText(/تا سطح «طلایی»/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'دریافت اعتبار ۵ هزار' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'دریافت اعتبار ۵۰ هزار' })).toBeDisabled();
    expect(screen.getByText('امتیاز کافی نیست')).toBeInTheDocument();
  });

  it('renders nothing for a store without a club', async () => {
    const coreFetch = vi.fn(async () => res({ store_id: 's1', enabled: false }));
    const { container } = render(<Loyalty coreFetch={coreFetch} storeId="s1" notify={vi.fn()} />);
    await waitFor(() => expect(coreFetch).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it('redeems with an Idempotency-Key and reloads the club', async () => {
    const seen = [];
    let balance = 700;
    const coreFetch = vi.fn(async (path, opts) => {
      if (opts?.method === 'POST') {
        seen.push([path, opts.headers['Idempotency-Key']]);
        balance = 200;
        return res({ id: 'x', balance });
      }
      return res(club({ balance }));
    });
    const notify = vi.fn();
    render(<Loyalty coreFetch={coreFetch} storeId="s1" notify={notify} />);
    await userEvent.click(await screen.findByRole('button', { name: 'دریافت اعتبار ۵ هزار' }));
    await waitFor(() => expect(screen.getByTestId('loyalty-balance')).toHaveTextContent('۲۰۰'));
    expect(seen).toHaveLength(1);
    expect(seen[0][0]).toBe('/api/v1/stores/s1/loyalty/rewards/r1/redeem');
    expect(seen[0][1].length).toBeGreaterThanOrEqual(8);
    expect(notify).toHaveBeenCalledWith(expect.stringContaining('کیف پول'));
  });

  it('shows the Core error message when redeeming fails', async () => {
    const coreFetch = vi.fn(async (_p, opts) =>
      opts?.method === 'POST' ? res({ error: { message: 'سقف دریافت پر شده است.' } }, 400) : res(club()),
    );
    const notify = vi.fn();
    render(<Loyalty coreFetch={coreFetch} storeId="s1" notify={notify} />);
    await userEvent.click(await screen.findByRole('button', { name: 'دریافت اعتبار ۵ هزار' }));
    await waitFor(() => expect(notify).toHaveBeenCalledWith('سقف دریافت پر شده است.'));
  });

  it('tells the customer about a points debt after a refund', async () => {
    const coreFetch = vi.fn(async () => res(club({ debt: 80 })));
    render(<Loyalty coreFetch={coreFetch} storeId="s1" notify={vi.fn()} />);
    expect(await screen.findByTestId('loyalty-debt')).toHaveTextContent('۸۰');
  });
});
