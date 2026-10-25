import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ResellerBankSms from '../src/ResellerBankSms.jsx';

const res = (body, status = 200) => new Response(JSON.stringify(body), { status });
const BASE = '/api/v1/stores/s1/reseller';

const source = (over = {}) => ({
  store_id: 's1',
  configured: true,
  bank: 'mehr_iran',
  is_enabled: true,
  auto_verify: true,
  has_token: true,
  token_hint: 'ab12',
  senders: [],
  settings: { window_minutes: 720, time_tolerance_minutes: 2, require_claimed_time: true, max_auto_amount_rial: null },
  last_received_at: null,
  ...over,
});
const sms = (over = {}) => ({
  id: 'm1',
  status: 'unmatched',
  direction: 'deposit',
  amount_rial: 1500000,
  occurred_at: '2026-10-24T19:20:00Z',
  serial: '302570009152325001',
  balance_gap: false,
  ...over,
});

function setup({ src = source(), messages = [sms()], payments = [], put } = {}) {
  const calls = [];
  const coreFetch = vi.fn(async (path, o = {}) => {
    calls.push([o.method || 'GET', path, o.body]);
    if (path.startsWith(`${BASE}/payments`)) return res(payments);
    if (path.endsWith('/receipt-review')) return res({ error: 'n/a' }, 404);
    if (o.method === 'PUT') return put ? put() : res({ source: src, token: null });
    if (o.method === 'POST') return res({ ok: true, matched: 1 });
    return res({ source: src, messages });
  });
  const notify = vi.fn();
  render(<ResellerBankSms coreFetch={coreFetch} base={BASE} notify={notify} />);
  return { calls, notify };
}

describe('reseller bank-SMS auto verification', () => {
  it('shows the forwarded deposit SMS with its serial and a human-readable status', async () => {
    setup();
    expect(await screen.findByText('302570009152325001')).toBeInTheDocument();
    expect(screen.getAllByText('در انتظار رسید').length).toBeGreaterThan(0);
  });

  it('offers only same-amount receipts waiting for review when pairing a deposit by hand', async () => {
    setup({
      payments: [
        {
          id: 'p1',
          status: 'awaiting_review',
          has_receipt: true,
          amount: 150000,
          currency: 'IRT',
          created_at: '2026-10-24T19:10:00Z',
        },
        {
          id: 'p2',
          status: 'awaiting_review',
          has_receipt: true,
          amount: 999,
          currency: 'IRT',
          created_at: '2026-10-24T19:11:00Z',
        },
        {
          id: 'p3',
          status: 'succeeded',
          has_receipt: true,
          amount: 150000,
          currency: 'IRT',
          created_at: '2026-10-24T19:12:00Z',
        },
      ],
    });
    const select = await screen.findByLabelText('اتصال به پرداخت');
    expect(select.querySelectorAll('option')).toHaveLength(2); // placeholder + p1 only
  });

  it('pairs only after confirmation and sends the chosen payment id', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const { calls } = setup({
      payments: [
        {
          id: 'p1',
          status: 'awaiting_review',
          has_receipt: true,
          amount: 150000,
          currency: 'IRT',
          created_at: '2026-10-24T19:10:00Z',
        },
      ],
    });
    await userEvent.selectOptions(await screen.findByLabelText('اتصال به پرداخت'), 'p1');
    await waitFor(() => expect(calls.some(([m, p]) => m === 'POST' && p === `${BASE}/bank-sms/m1/link`)).toBe(true));
    const post = calls.find(([, p]) => p.endsWith('/m1/link'));
    expect(JSON.parse(post[2])).toEqual({ payment_id: 'p1' });
  });

  it('shows the one-time webhook token returned by the first activation', async () => {
    const { notify } = setup({
      src: source({ configured: false, is_enabled: false, auto_verify: false, has_token: false, token_hint: null }),
      messages: [],
      put: () => res({ source: source(), token: 'mlr_sms_SECRET' }),
    });
    await userEvent.click(await screen.findByRole('button', { name: /فعال‌سازی و ساخت توکن/ }));
    expect(await screen.findByText('mlr_sms_SECRET')).toBeInTheDocument();
    expect(notify).toHaveBeenCalled();
  });

  it('flags a balance gap so a missed SMS is noticed', async () => {
    setup({ messages: [sms({ balance_gap: true })] });
    expect(await screen.findByText(/مانده با پیامک قبلی نمی‌خواند/)).toBeInTheDocument();
  });
});
