import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Coupons from '../src/features/coupons/CouponsView.tsx';

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });

const MAIN = { id: 'store-1', name: 'فروشگاه اصلی', kind: 'main', currency: 'IRT' };
const SHOP = { id: 'store-2', name: 'نمایندگی الف', kind: 'reseller', currency: 'IRR' };

/** A row exactly as Core's CouponOut declares it. */
const coupon = (over = {}) => ({
  id: 'coupon-1',
  code: 'WELCOME',
  scope: 'store',
  store_id: 'store-1',
  allowed_store_ids: null,
  allowed_store_kinds: null,
  product_ids: null,
  creator_type: 'admin',
  funded_by: 'platform',
  percent_bp: 1000,
  fixed: 0,
  max_discount: null,
  min_amount: 0,
  currency: 'IRT',
  starts_at: null,
  ends_at: null,
  max_redemptions: 10,
  per_customer_limit: 1,
  redemptions: 3,
  combinable: false,
  status: 'active',
  ...over,
});

/** Fake Core. `couponsFor(storeId)` answers the list; `reply` may override any request (return undefined to fall through). */
function setup({ stores = [MAIN], couponsFor = () => [], reply = () => undefined } = {}) {
  const calls = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, options = {}) => {
    const parsed = new URL(String(url));
    const path = parsed.pathname;
    const method = options.method || 'GET';
    calls.push({ method, path, query: parsed.search, body: options.body });
    const custom = await reply({ method, path, parsed });
    if (custom) return custom;
    if (path === '/api/v1/admin/stores') return json(stores);
    if (path === '/api/v1/admin/coupons' && method === 'GET')
      return json(couponsFor(parsed.searchParams.get('store_id')));
    if (path === '/api/v1/admin/coupons' && method === 'POST') return json(coupon({ id: 'coupon-new' }), 201);
    if (/^\/api\/v1\/admin\/coupons\/[^/]+$/.test(path) && method === 'PATCH') return json(coupon());
    return json({ detail: 'unexpected request' }, 404);
  });
  const toast = vi.fn();
  render(<Coupons api={{ base: 'http://core.test' }} toast={toast} />);
  const listCalls = () => calls.filter((c) => c.method === 'GET' && c.path === '/api/v1/admin/coupons');
  return { calls, toast, listCalls };
}

async function openForm() {
  await screen.findByText('کوپن‌ها');
  await userEvent.click(screen.getByRole('button', { name: /افزودن کوپن/ }));
}
const submit = () => userEvent.click(screen.getAllByRole('button', { name: /افزودن کوپن/ }).at(-1));

describe('admin coupons typed API contract', () => {
  it('sends a schema-checked create payload and reloads the selected store coupons', async () => {
    const { calls, toast, listCalls } = setup();
    await openForm();
    await userEvent.type(screen.getByLabelText('کد'), ' WELCOME ');
    await userEvent.type(screen.getByLabelText('درصد تخفیف'), '10');
    await userEvent.type(screen.getByLabelText('تخفیف ثابت'), '5000');
    await userEvent.type(screen.getByLabelText('سقف مبلغ تخفیف'), '20000');
    await userEvent.type(screen.getByLabelText('حداقل مبلغ سفارش'), '1000');
    await userEvent.type(screen.getByLabelText('سقف استفاده'), '25');
    await userEvent.type(screen.getByLabelText(/هر مشتری/), '2');
    fireEvent.change(screen.getByLabelText('تاریخ پایان'), { target: { value: '2999-01-01' } });
    await submit();
    await waitFor(() => expect(toast).toHaveBeenCalledWith('کوپن ساخته شد'));
    const create = calls.find((c) => c.method === 'POST' && c.path === '/api/v1/admin/coupons');
    expect(JSON.parse(create.body)).toEqual({
      code: 'WELCOME',
      percent_bp: 1000,
      fixed: 5000,
      min_amount: 1000,
      max_discount: 20000,
      max_redemptions: 25,
      per_customer_limit: 2,
      ends_at: new Date('2999-01-01T23:59:59').toISOString(),
      scope: 'store',
      store_id: 'store-1',
      funded_by: 'platform',
      status: 'active',
    });
    await waitFor(() => expect(listCalls()).toHaveLength(2));
    expect(listCalls().every((c) => c.query === '?store_id=store-1')).toBe(true);
  });

  it('defaults the optional fields the way Core does', async () => {
    const { calls, toast } = setup();
    await openForm();
    await userEvent.type(screen.getByLabelText('کد'), 'SIMPLE');
    await userEvent.type(screen.getByLabelText('درصد تخفیف'), '15.5');
    await submit();
    await waitFor(() => expect(toast).toHaveBeenCalledWith('کوپن ساخته شد'));
    expect(JSON.parse(calls.find((c) => c.method === 'POST').body)).toMatchObject({
      code: 'SIMPLE',
      percent_bp: 1550,
      fixed: 0,
      min_amount: 0,
      max_discount: null,
      max_redemptions: null,
      per_customer_limit: 1,
      ends_at: null,
    });
  });

  it('stops an invalid form before it reaches the network and says why', async () => {
    const { calls, toast } = setup();
    await openForm();
    await userEvent.type(screen.getByLabelText('کد'), 'ab');
    await userEvent.type(screen.getByLabelText('درصد تخفیف'), '10');
    await submit();
    expect(toast).toHaveBeenCalledWith(expect.stringContaining('۳ تا ۵۰ نویسه'));
    await userEvent.clear(screen.getByLabelText('کد'));
    await userEvent.type(screen.getByLabelText('کد'), 'GOOD10');
    await userEvent.clear(screen.getByLabelText('درصد تخفیف'));
    await submit();
    expect(toast).toHaveBeenLastCalledWith('تخفیف باید درصدی یا مبلغ ثابت داشته باشد.');
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
  });

  it("shows Core's own reason when the create is refused and keeps the form open", async () => {
    const { toast } = setup({
      reply: ({ method, path }) =>
        method === 'POST' && path === '/api/v1/admin/coupons'
          ? json({ error: { code: 'COUPON_EXISTS', message: 'این کد تخفیف قبلاً ساخته شده است.' } }, 409)
          : undefined,
    });
    await openForm();
    await userEvent.type(screen.getByLabelText('کد'), 'WELCOME');
    await userEvent.type(screen.getByLabelText('درصد تخفیف'), '10');
    await submit();
    await waitFor(() => expect(toast).toHaveBeenCalledWith('این کد تخفیف قبلاً ساخته شده است.'));
    expect(screen.getByLabelText('کد')).toHaveValue('WELCOME');
  });

  it('says so when the server cannot be reached', async () => {
    const { toast } = setup({
      reply: ({ method, path }) => {
        if (method === 'POST' && path === '/api/v1/admin/coupons') throw new TypeError('network down');
      },
    });
    await openForm();
    await userEvent.type(screen.getByLabelText('کد'), 'WELCOME');
    await userEvent.type(screen.getByLabelText('درصد تخفیف'), '10');
    await submit();
    await waitFor(() => expect(toast).toHaveBeenCalledWith('ارتباط با سرور برقرار نشد'));
  });

  it('uses a templated typed path and path params when toggling a coupon', async () => {
    const { calls } = setup({ couponsFor: () => [coupon()] });
    await userEvent.click(await screen.findByRole('button', { name: 'غیرفعال' }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'PATCH' && c.path === '/api/v1/admin/coupons/coupon-1')).toBe(true),
    );
    expect(JSON.parse(calls.find((c) => c.method === 'PATCH').body)).toEqual({ status: 'disabled' });
  });

  it('switches a disabled or archived coupon back on', async () => {
    const { calls } = setup({
      couponsFor: () => [coupon({ id: 'coupon-9', code: 'OLD', status: 'archived' })],
    });
    await userEvent.click(await screen.findByRole('button', { name: 'فعال' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    expect(calls.find((c) => c.method === 'PATCH').path).toBe('/api/v1/admin/coupons/coupon-9');
    expect(JSON.parse(calls.find((c) => c.method === 'PATCH').body)).toEqual({ status: 'active' });
  });

  it("shows Core's reason when a status change is refused", async () => {
    const { toast } = setup({
      couponsFor: () => [coupon()],
      reply: ({ method }) =>
        method === 'PATCH'
          ? json({ error: { code: 'COUPON_BAD_WINDOW', message: 'بازه اعتبار نامعتبر است.' } }, 400)
          : undefined,
    });
    await userEvent.click(await screen.findByRole('button', { name: 'غیرفعال' }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith('بازه اعتبار نامعتبر است.'));
  });

  it('lists the real CouponOut fields: owner store, currency and redemptions', async () => {
    setup({
      stores: [MAIN, SHOP],
      couponsFor: () => [
        coupon({ code: 'MAINONLY', fixed: 5000, percent_bp: 0, redemptions: 3, max_redemptions: 10 }),
        coupon({
          id: 'coupon-2',
          code: 'ALLSHOPS',
          scope: 'domain',
          store_id: null,
          currency: null,
          max_redemptions: null,
          redemptions: 0,
        }),
      ],
    });
    const row = (await screen.findByText('MAINONLY')).closest('tr');
    expect(row).toHaveTextContent('فروشگاه اصلی');
    expect(row).toHaveTextContent('۵٬۰۰۰ IRT');
    expect(row).toHaveTextContent('۳/۱۰');
    const domain = screen.getByText('ALLSHOPS').closest('tr');
    expect(domain).toHaveTextContent('چندفروشگاهی');
    expect(domain).toHaveTextContent('۰/∞');
  });

  it('asks for the default store once instead of an unfiltered list followed by a filtered one', async () => {
    const { listCalls } = setup({ stores: [SHOP, MAIN] });
    await waitFor(() => expect(listCalls()).toHaveLength(1));
    expect(listCalls()[0].query).toBe('?store_id=store-1');
  });

  it('never shows the answer of a store the admin already left', async () => {
    let releaseStale;
    const { listCalls } = setup({
      stores: [MAIN, SHOP],
      couponsFor: (storeId) => [coupon({ code: storeId === 'store-1' ? 'FROM-MAIN' : 'FROM-SHOP' })],
      reply: async ({ method, path, parsed }) => {
        if (method === 'GET' && path === '/api/v1/admin/coupons' && parsed.searchParams.get('store_id') === 'store-1')
          await new Promise((resolve) => (releaseStale = resolve));
      },
    });
    await waitFor(() => expect(listCalls()).toHaveLength(1)); // the main store's answer is still in flight
    await userEvent.selectOptions(await screen.findByLabelText('فروشگاه'), 'store-2');
    expect(await screen.findByText('FROM-SHOP')).toBeInTheDocument();
    releaseStale();
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(screen.queryByText('FROM-MAIN')).not.toBeInTheDocument();
    expect(screen.getByText('FROM-SHOP')).toBeInTheDocument();
  });

  it('shows "all stores" without a filter and still loads when the store list fails', async () => {
    const { listCalls, toast } = setup({
      reply: ({ path }) => (path === '/api/v1/admin/stores' ? json({ detail: 'boom' }, 500) : undefined),
      couponsFor: () => [coupon({ code: 'ANYSTORE' })],
    });
    expect(await screen.findByText('ANYSTORE')).toBeInTheDocument();
    expect(toast).toHaveBeenCalledWith('دریافت فهرست فروشگاه‌ها ناموفق بود');
    expect(listCalls()[0].query).toBe('');
  });

  it('offers a retry when the coupon list cannot be loaded', async () => {
    let healthy = false;
    const { listCalls } = setup({
      reply: ({ method, path }) =>
        method === 'GET' && path === '/api/v1/admin/coupons' && !healthy ? json({ detail: 'down' }, 503) : undefined,
      couponsFor: () => [coupon({ code: 'BACKAGAIN' })],
    });
    const retry = await screen.findByRole('button', { name: 'تلاش دوباره' });
    healthy = true;
    await userEvent.click(retry);
    expect(await screen.findByText('BACKAGAIN')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(listCalls().length).toBeGreaterThanOrEqual(2);
  });
});
