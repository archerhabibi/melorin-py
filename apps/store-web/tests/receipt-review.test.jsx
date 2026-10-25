import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ResellerReceiptReview, { clock } from '../src/ResellerReceiptReview.jsx';

const res = (body, status = 200) => new Response(JSON.stringify(body), { status });
const BASE = '/api/v1/stores/s1/reseller';
const NOW = new Date();
const iso = (sec) => new Date(NOW.getTime() + sec * 1000).toISOString();
const item = (over = {}) => ({
  payment_id: 'p1',
  amount: 150000,
  currency: 'IRT',
  state: 'waiting',
  block: null,
  block_text: null,
  auto_approve_at: iso(240),
  receipt_read: { amount_rial: 1500000, source_card_last4: '7931' },
  ...over,
});
const queue = (over = {}) => ({
  config: { enabled: true, minutes: 5, max_amount_rial: 5000000, max_exposure_rial: 20000000, max_open_per_user: 1 },
  now: NOW.toISOString(),
  waiting: [item()],
  provisional: [],
  recent: [],
  exposure_rial: 0,
  ...over,
});
function setup(q = queue()) {
  const calls = [];
  const coreFetch = vi.fn(async (path, o = {}) => {
    calls.push([o.method || 'GET', path, o.body]);
    return o.method ? res({ ok: true }) : res(q);
  });
  render(<ResellerReceiptReview coreFetch={coreFetch} base={BASE} notify={vi.fn()} />);
  return { calls };
}

describe('reseller receipt review', () => {
  it('formats the countdown', () => {
    expect(clock(65)).toBe('۰۱:۰۵');
    expect(clock(-1)).toBe('۰۰:۰۰');
  });
  it('shows the waiting receipt with a countdown', async () => {
    setup();
    expect(await screen.findByText(/تا تأیید موقت/)).toBeInTheDocument();
    expect(screen.getByText('…7931')).toBeInTheDocument();
  });
  it('revokes a provisional credit only after the owner confirms', async () => {
    const { calls } = setup(queue({ waiting: [], provisional: [item({ state: 'open', auto_approve_at: null })] }));
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    await userEvent.click(await screen.findByRole('button', { name: /لغو و برگشت اعتبار/ }));
    await waitFor(() => expect(calls.some(([m]) => m === 'POST')).toBe(true));
    const post = calls.find(([m]) => m === 'POST');
    expect(post[1]).toBe(`${BASE}/receipt-review/p1`);
    expect(JSON.parse(post[2])).toEqual({ approve: false });
  });
  it('renders nothing against an older server', async () => {
    const coreFetch = vi.fn(async () => res({ error: 'x' }, 404));
    const { container } = render(<ResellerReceiptReview coreFetch={coreFetch} base={BASE} notify={vi.fn()} />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});
