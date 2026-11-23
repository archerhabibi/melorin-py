import { beforeEach, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Vpn } from '../src/dashboard/DashboardAccounts.tsx';

// Browser tests exercise IndexedDB locking; these tests isolate request and UI behavior.
vi.mock('../src/attemptLock.ts', () => ({ withAttemptLock: async (operation) => operation() }));

vi.mock('../src/AccountInquiry.tsx', () => ({
  default: ({ renderExtra }) => <div>{renderExtra({ id: 'vpn1', can_renew: true, is_test: false })}</div>,
}));

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });

beforeEach(() => localStorage.clear());

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
  await userEvent.click(await screen.findByRole('button', { name: 'پرداخت از کیف پول و تمدید' }));
  await waitFor(() => expect(notify).toHaveBeenCalledWith('نامعلوم'));
  await userEvent.click(screen.getByRole('button', { name: 'بستن' }));
  await userEvent.click(screen.getByRole('button', { name: 'تمدید' }));
  await userEvent.click(await screen.findByRole('button', { name: 'پرداخت از کیف پول و تمدید' }));
  await waitFor(() => expect(keys).toHaveLength(2));
  expect(keys[1]).toBe(keys[0]);
});
