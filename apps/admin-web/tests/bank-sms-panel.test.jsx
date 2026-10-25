import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import BankSmsPanel from '../src/BankSmsPanel.jsx';
import { DialogHost } from '../src/ui.jsx';

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const STORE = 's-main';
const BASE = `/api/v1/admin/stores/${STORE}/bank-sms`;

const source = (over = {}) => ({
  store_id: STORE,
  configured: true,
  is_enabled: true,
  auto_verify: true,
  token_hint: 'ab12',
  senders: [],
  settings: { window_minutes: 720, time_tolerance_minutes: 2, require_claimed_time: true, max_auto_amount_rial: null },
  last_received_at: null,
  ...over,
});
const deposit = (over = {}) => ({
  id: 'm1',
  status: 'ambiguous',
  direction: 'deposit',
  amount_rial: 1500000,
  occurred_at: '2026-10-24T19:20:00Z',
  serial: '302570009152325001',
  balance_gap: false,
  ...over,
});
const waiting = {
  id: 'p1',
  provider: 'manual_card',
  status: 'awaiting_review',
  has_receipt: true,
  amount: 150000,
  currency: 'IRT',
  created_at: '2026-10-24T19:10:00Z',
};

function setup({ src = source(), messages = [deposit()], put } = {}) {
  const calls = [];
  const call = vi.fn(async (path, o = {}) => {
    calls.push([o.method || 'GET', path, o.body]);
    if (path === '/api/v1/me/stores') return json([{ id: STORE, kind: 'main' }]);
    if (path.endsWith('/receipt-review')) return json({ error: 'n/a' }, 404);
    if (o.method === 'PUT') return put ? put() : json({ source: src, token: null });
    if (o.method === 'POST') return json({ ok: true, matched: 0 });
    return json({ source: src, messages });
  });
  const toast = vi.fn();
  render(
    <>
      <BankSmsPanel call={call} toast={toast} payments={[waiting, { ...waiting, id: 'p2', amount: 5 }]} />
      <DialogHost />
    </>,
  );
  return { calls, toast };
}

describe('admin bank-SMS auto verification panel', () => {
  it('targets the main store and lists the ambiguous deposit for a human decision', async () => {
    const { calls } = setup();
    expect(await screen.findByText('302570009152325001')).toBeInTheDocument();
    expect(screen.getAllByText('نیاز به بررسی').length).toBeGreaterThan(0);
    expect(calls.some(([m, p]) => m === 'GET' && p === BASE)).toBe(true);
  });

  it('offers only the receipt with the same amount when pairing', async () => {
    setup();
    const select = await screen.findByLabelText('اتصال به پرداخت');
    expect(select.querySelectorAll('option')).toHaveLength(2); // placeholder + p1 (p2 has another amount)
  });

  it('shows the one-time token after the first activation and never asks for it again', async () => {
    setup({
      src: source({ configured: false, is_enabled: false, auto_verify: false, token_hint: null }),
      messages: [],
      put: () => json({ source: source(), token: 'mlr_sms_SECRET' }),
    });
    await userEvent.click(await screen.findByRole('button', { name: /فعال‌سازی و ساخت توکن/ }));
    expect(await screen.findByText('mlr_sms_SECRET')).toBeInTheDocument();
  });

  it('sends the tuning settings as integers (Persian digits accepted)', async () => {
    const { calls } = setup();
    const win = await screen.findByLabelText(/بازه‌ی پذیرش/);
    await userEvent.clear(win);
    await userEvent.type(win, '۳۶۰');
    await userEvent.click(screen.getByRole('button', { name: 'ذخیره' }));
    await waitFor(() => expect(calls.some(([m]) => m === 'PUT')).toBe(true));
    const put = calls.find(([m]) => m === 'PUT');
    expect(put[1]).toBe(`${BASE}/source`);
    expect(JSON.parse(put[2]).settings.window_minutes).toBe(360);
  });
});
