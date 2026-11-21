import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import BankSmsPanel from '../src/features/payments/BankSmsPanel.tsx';
import { DialogHost } from '../src/shared/ui.tsx';

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
  const requests = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url, init = {}) => {
      const target = String(url);
      requests.push([target, init]);
      if (target.endsWith('/api/v1/me/stores')) return json([{ id: STORE, kind: 'main' }]);
      if (target.includes('/bank-sms/source') && init.method === 'PUT')
        return put ? put() : json({ source: src, token: null });
      if (target.includes('/bank-sms/token') && init.method === 'POST') return json({ token: 'mlr_sms_SECRET' });
      if (target.includes('/bank-sms/reconcile') && init.method === 'POST') return json({ ok: true, matched: 0 });
      if (target.includes('/bank-sms') && !target.includes('/receipt-review')) return json({ source: src, messages });
      return json({ error: 'n/a' }, 404);
    }),
  );
  const call = vi.fn(async (path, o = {}) => {
    calls.push([o.method || 'GET', path, o.body]);
    if (path.endsWith('/receipt-review')) return json({ error: 'n/a' }, 404);
    return json({ ok: true });
  });
  const toast = vi.fn();
  render(
    <>
      <BankSmsPanel call={call} toast={toast} payments={[waiting, { ...waiting, id: 'p2', amount: 5 }]} />
      <DialogHost />
    </>,
  );
  return { calls, requests, toast };
}

describe('admin bank-SMS auto verification panel', () => {
  afterEach(() => vi.unstubAllGlobals());
  it('targets the main store and lists the ambiguous deposit for a human decision', async () => {
    const { requests } = setup();
    expect(await screen.findByText('302570009152325001')).toBeInTheDocument();
    expect(screen.getAllByText('نیاز به بررسی').length).toBeGreaterThan(0);
    expect(requests.some(([url, init]) => url.includes(BASE) && !init.method)).toBe(true);
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
    const { requests } = setup();
    const win = await screen.findByLabelText(/بازه‌ی پذیرش/);
    await userEvent.clear(win);
    await userEvent.type(win, '۳۶۰');
    await userEvent.click(screen.getByRole('button', { name: 'ذخیره' }));
    await waitFor(() =>
      expect(requests.some(([url, init]) => url.includes(`${BASE}/source`) && init.method === 'PUT')).toBe(true),
    );
    const put = requests.find(([url, init]) => url.includes(`${BASE}/source`) && init.method === 'PUT');
    expect(JSON.parse(put[1].body).settings.window_minutes).toBe(360);
  });
});
