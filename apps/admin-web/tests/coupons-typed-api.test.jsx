import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Coupons from '../src/features/coupons/CouponsView.tsx';

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });

function setup(couponRows = []) {
  const calls = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, options = {}) => {
    const parsed = new URL(String(url));
    const path = parsed.pathname;
    calls.push({ method: options.method || 'GET', path, query: parsed.search, body: options.body });
    if (path === '/api/v1/admin/stores')
      return json([{ id: 'store-1', name: 'فروشگاه اصلی', kind: 'main', currency: 'IRT' }]);
    if (path === '/api/v1/admin/coupons' && (options.method || 'GET') === 'GET') return json(couponRows);
    if (path === '/api/v1/admin/coupons' && options.method === 'POST') return json({ id: 'coupon-1' }, 201);
    if (path === '/api/v1/admin/coupons/coupon-1' && options.method === 'PATCH') return json({ id: 'coupon-1' });
    return json({ detail: 'unexpected request' }, 404);
  });
  const toast = vi.fn();
  render(<Coupons api={{ base: 'http://core.test' }} toast={toast} />);
  return { calls, toast };
}

describe('admin coupons typed API contract', () => {
  it('sends a schema-checked create payload and reloads the selected store coupons', async () => {
    const { calls, toast } = setup();
    await screen.findByText('کوپن‌ها');
    await userEvent.click(screen.getByRole('button', { name: /افزودن کوپن/ }));
    await userEvent.type(screen.getByLabelText('کد'), 'WELCOME');
    await userEvent.type(screen.getByLabelText('درصد تخفیف'), '10');
    await userEvent.type(screen.getByLabelText('تخفیف ثابت'), '5000');
    await userEvent.type(screen.getByLabelText('سقف استفاده'), '25');
    await userEvent.click(screen.getAllByRole('button', { name: /افزودن کوپن/ }).at(-1));
    await waitFor(() => expect(toast).toHaveBeenCalledWith('کوپن ساخته شد'));
    const create = calls.find((call) => call.method === 'POST' && call.path === '/api/v1/admin/coupons');
    expect(JSON.parse(create.body)).toEqual({
      code: 'WELCOME',
      percent_bp: 1000,
      fixed: 5000,
      max_redemptions: 25,
      scope: 'store',
      store_id: 'store-1',
      funded_by: 'platform',
      min_amount: 0,
      per_customer_limit: 1,
      status: 'active',
    });
    expect(
      calls.some(
        (call) => call.method === 'GET' && call.path === '/api/v1/admin/coupons' && call.query === '?store_id=store-1',
      ),
    ).toBe(true);
  });

  it('uses a templated typed path and path params when toggling a coupon', async () => {
    const { calls } = setup([
      {
        id: 'coupon-1',
        code: 'WELCOME',
        percent_bp: 1000,
        fixed: 0,
        redeemed: 0,
        max_redemptions: 10,
        status: 'active',
      },
    ]);
    await userEvent.click(await screen.findByRole('button', { name: 'غیرفعال' }));
    await waitFor(() =>
      expect(calls.some((call) => call.method === 'PATCH' && call.path === '/api/v1/admin/coupons/coupon-1')).toBe(
        true,
      ),
    );
    const patch = calls.find((call) => call.method === 'PATCH');
    expect(JSON.parse(patch.body)).toEqual({ status: 'disabled' });
  });
});
