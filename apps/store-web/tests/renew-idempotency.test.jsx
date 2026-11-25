import { beforeEach, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Vpn } from '../src/dashboard/DashboardAccounts.tsx';
import { submitOrder } from '../src/orderRequest.ts';
import { resetAttemptStorage } from './attemptStorage.js';

const accountCard = vi.hoisted(() => ({ canRenew: true }));
vi.mock('../src/AccountInquiry.tsx', () => ({
  default: ({ renderExtra }) => (
    <div>{renderExtra({ id: 'vpn1', can_renew: accountCard.canRenew, is_test: false })}</div>
  ),
}));

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });

beforeEach(async () => {
  await resetAttemptStorage();
  accountCard.canRenew = true;
});

it('reuses a renewal key when the customer closes and reopens an uncertain attempt', async () => {
  const keys = [];
  const coreFetch = vi.fn(async (path, options = {}) => {
    if (path.endsWith('/renewal')) return json({ renewable: true, package: { product_id: 'p1', name: 'Plan' } });
    if (path.endsWith('/checkout/quote')) return json({ total: 100, currency: 'IRT', sufficient_funds: true });
    if (path.endsWith('/orders')) {
      keys.push(options.headers['Idempotency-Key']);
      return keys.length === 1 ? json({ error: { message: 'نامعلوم' } }, 503) : json({ id: 'o1' });
    }
    return json([]);
  });
  const notify = vi.fn();
  render(<Vpn coreFetch={coreFetch} storeId="s1" userId="u1" notify={notify} reload={() => {}} />);
  await userEvent.click(screen.getByRole('button', { name: 'تمدید' }));
  const pay = await screen.findByRole('button', { name: 'پرداخت از کیف پول و تمدید' });
  await waitFor(() => expect(pay).toBeEnabled());
  await userEvent.click(pay);
  await waitFor(() => expect(notify).toHaveBeenCalledWith('نامعلوم'));
  await userEvent.click(screen.getByRole('button', { name: 'بستن' }));
  await userEvent.click(screen.getByRole('button', { name: 'تمدید' }));
  await userEvent.click(await screen.findByRole('button', { name: 'تلاش مجدد تمدید قبلی' }));
  await waitFor(() => expect(keys).toHaveLength(2));
  expect(keys[1]).toBe(keys[0]);
});

it('recovers an uncertain renewal even after the account becomes ineligible', async () => {
  const keys = [];
  const coreFetch = vi.fn(async (path, options = {}) => {
    if (path.endsWith('/renewal')) {
      return keys.length
        ? json({ renewable: false, code: 'RENEWAL_IN_PROGRESS' })
        : json({ renewable: true, package: { product_id: 'p1', name: 'Plan' } });
    }
    if (path.endsWith('/checkout/quote')) return json({ total: 100, currency: 'IRT', sufficient_funds: true });
    if (path.endsWith('/orders')) {
      keys.push(options.headers['Idempotency-Key']);
      return keys.length === 1 ? json({ error: { message: 'نامعلوم' } }, 503) : json({ id: 'o1' });
    }
    return json([]);
  });
  const notify = vi.fn();
  const { unmount } = render(<Vpn coreFetch={coreFetch} storeId="s1" userId="u1" notify={notify} reload={() => {}} />);
  await userEvent.click(screen.getByRole('button', { name: 'تمدید' }));
  const pay = await screen.findByRole('button', { name: 'پرداخت از کیف پول و تمدید' });
  await waitFor(() => expect(pay).toBeEnabled());
  await userEvent.click(pay);
  await waitFor(() => expect(notify).toHaveBeenCalledWith('نامعلوم'));
  unmount();
  accountCard.canRenew = false;
  render(<Vpn coreFetch={coreFetch} storeId="s1" userId="u1" notify={notify} reload={() => {}} />);
  await userEvent.click(await screen.findByRole('button', { name: 'پیگیری تمدید قبلی' }));
  await userEvent.click(await screen.findByRole('button', { name: 'تلاش مجدد تمدید قبلی' }));
  await waitFor(() => expect(keys).toHaveLength(2));
  expect(keys[1]).toBe(keys[0]);
});

it('shows an uncertain renewal created in another tab', async () => {
  accountCard.canRenew = false;
  const coreFetch = vi.fn(async () => json({ error: { message: 'نامعلوم' } }, 503));
  render(<Vpn coreFetch={coreFetch} storeId="s1" userId="u1" notify={vi.fn()} reload={() => {}} />);
  await submitOrder({
    coreFetch,
    storeId: 's1',
    accountId: 'u1',
    body: { product_id: 'p1', payment_method: 'wallet', kind: 'renewal', vpn_account_id: 'vpn1' },
  });
  await act(async () => {
    window.dispatchEvent(new StorageEvent('storage', { key: 'melorin:order-attempt:s1:u1:pending' }));
  });
  expect(await screen.findByRole('button', { name: 'پیگیری تمدید قبلی' })).toBeVisible();
});
