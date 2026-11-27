import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PaymentsView from '../src/features/payments/PaymentsView.tsx';
import { DialogHost } from '../src/shared/ui.tsx';

// The payments screen is a hub of four tabs (transactions / receipts / bank SMS / gateways). Each tab owns what it
// fetches, so nothing about gateways or SMS is requested while the admin is only looking at transactions.

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const STORE = 's-main';
const pay = (id, over = {}) => ({
  id,
  user_id: 'u1',
  store_id: STORE,
  provider: 'manual_card',
  amount: 150000,
  currency: 'IRT',
  status: 'awaiting_review',
  has_receipt: true,
  created_at: '2026-10-24T19:10:00Z',
  ...over,
});
const PAYMENTS = [pay('p1'), pay('p2'), pay('p3', { status: 'succeeded' })];
const reviewQueue = (provisional = []) => ({
  config: {
    enabled: true,
    minutes: 5,
    max_amount_rial: 5000000,
    max_exposure_rial: 20000000,
    max_open_per_user: 1,
  },
  now: '2026-10-25T10:00:00Z',
  waiting: [],
  provisional,
  recent: [],
  exposure_rial: 0,
});
const provisionalItem = (id) => ({
  payment_id: id,
  user_id: 'u1',
  amount: 150000,
  currency: 'IRT',
  created_at: '2026-10-25T09:50:00Z',
  state: 'provisional',
  block: null,
  block_text: null,
  auto_approve_at: null,
  receipt_read: null,
});

let requests;
function setup({ provisional = [] } = {}) {
  requests = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url, init = {}) => {
      const path = new URL(String(url), 'http://x').pathname;
      requests.push(path);
      if (path === '/api/v1/me/stores') return json([{ id: STORE, kind: 'main' }]);
      if (path === '/api/v1/admin/payments') return json(PAYMENTS);
      if (path === `/api/v1/admin/stores/${STORE}/receipt-review`) return json(reviewQueue(provisional));
      if (path === '/api/v1/admin/payment-destinations')
        return json([
          {
            provider: 'manual_card',
            public_config: { card_number: '6037991234567890', holder: 'علی رضایی', bank: 'ملی' },
          },
        ]);
      if (path === `/api/v1/admin/stores/${STORE}/bank-sms`)
        return json({
          source: {
            store_id: STORE,
            configured: false,
            is_enabled: false,
            auto_verify: false,
            token_hint: null,
            senders: [],
            settings: {
              window_minutes: 720,
              time_tolerance_minutes: 2,
              require_claimed_time: true,
              max_auto_amount_rial: null,
            },
            last_received_at: null,
          },
          messages: [],
        });
      return json({ error: 'n/a' }, 404);
    }),
  );
  const toast = vi.fn();
  render(
    <>
      <PaymentsView api={{ base: '' }} toast={toast} />
      <DialogHost />
    </>,
  );
  return { toast };
}
const tab = (name) => screen.getByRole('radio', { name: new RegExp(name) });

describe('payments hub', () => {
  beforeEach(() => {
    window.location.hash = '#/payments';
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.location.hash = '';
  });

  it('opens on the transactions tab and keeps the four sections apart', async () => {
    setup();
    expect(screen.getAllByRole('radio')).toHaveLength(4);
    expect(tab('تراکنش‌ها')).toHaveAttribute('aria-checked', 'true');
    expect(await screen.findByText('دریافتی موفق')).toBeInTheDocument();
    // none of the configuration screens is part of this tab any more
    expect(screen.queryByText('روش‌های دریافت فروشگاه اصلی')).not.toBeInTheDocument();
    expect(screen.queryByText(/تأیید خودکار کارت‌به‌کارت با پیامک بانک/)).not.toBeInTheDocument();
    expect(screen.queryByText('بازبینی سریع و تأیید موقت رسیدها')).not.toBeInTheDocument();
  });

  it('badges the transactions tab with the receipts waiting for a decision', async () => {
    setup();
    await waitFor(() => expect(tab('تراکنش‌ها')).toHaveTextContent('۲'));
  });

  it('badges the receipts tab with the provisional charges that need a final decision', async () => {
    setup({ provisional: [provisionalItem('p1'), provisionalItem('p2'), provisionalItem('p3')] });
    await waitFor(() => expect(tab('رسیدها')).toHaveTextContent('۳'));
  });

  it('loads the gateway settings only when the gateways tab is opened, and deep-links it', async () => {
    setup();
    await screen.findByText('دریافتی موفق');
    expect(requests).not.toContain('/api/v1/admin/payment-destinations');
    await userEvent.click(tab('درگاه‌ها'));
    expect(await screen.findByText('روش‌های دریافت فروشگاه اصلی')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'ذخیره اطلاعات کارت' })).toBeInTheDocument(); // forms are open, no accordion
    expect(requests).toContain('/api/v1/admin/payment-destinations');
    expect(window.location.hash).toBe('#/payments?tab=gateways');
  });

  it('opens the tab named by the URL', async () => {
    window.location.hash = '#/payments?tab=sms';
    setup();
    expect(tab('پیامک بانک')).toHaveAttribute('aria-checked', 'true');
    expect(await screen.findByText(/تأیید خودکار کارت‌به‌کارت با پیامک بانک/)).toBeInTheDocument();
    expect(screen.queryByText('دریافتی موفق')).not.toBeInTheDocument();
  });

  it('shows the fast receipt review on its own tab, and the way back drops the query', async () => {
    setup();
    await userEvent.click(tab('رسیدها'));
    expect(await screen.findByText('بازبینی سریع و تأیید موقت رسیدها')).toBeInTheDocument();
    expect(window.location.hash).toBe('#/payments?tab=receipts');
    await userEvent.click(tab('تراکنش‌ها'));
    expect(await screen.findByText('دریافتی موفق')).toBeInTheDocument();
    expect(window.location.hash).toBe('#/payments');
  });

  it('falls back to transactions for an unknown tab in the URL', async () => {
    window.location.hash = '#/payments?tab=nope';
    setup();
    expect(tab('تراکنش‌ها')).toHaveAttribute('aria-checked', 'true');
    expect(await screen.findByText('دریافتی موفق')).toBeInTheDocument();
  });
});
