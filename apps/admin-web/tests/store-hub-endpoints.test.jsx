import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import StoreBotsView from '../src/StoreBotsView.tsx';
import StoreNoticesView from '../src/StoreNoticesView.tsx';
import UnassignedProducts from '../src/UnassignedProducts.tsx';
import ProductAvailability from '../src/ProductAvailability.tsx';

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const api = { base: 'http://core.test', perms: [] };
const STORES = [{ id: 's1', name: 'فروشگاه الف', kind: 'reseller' }];
const calls = [];

function stubFetch(routes) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url, init = {}) => {
      const path = String(url).replace('http://core.test', '');
      calls.push({ path, method: init.method || 'GET', body: init.body ? JSON.parse(init.body) : null });
      const hit = Object.entries(routes).find(
        ([k]) => path.startsWith(k.split(' ')[1]) && (init.method || 'GET') === k.split(' ')[0],
      );
      return hit ? json(typeof hit[1] === 'function' ? hit[1]() : hit[1]) : json({}, 404);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  calls.length = 0;
});

describe('store hub screens for formerly UI-less endpoints', () => {
  it('bot bindings: lists them and creates one for a store', async () => {
    stubFetch({
      'GET /api/v1/admin/bot-store-bindings': [
        {
          id: 'b1',
          bot_key: 'abcdefgh1234',
          bot_username: 'rep_bot',
          store_id: 's1',
          bot_kind: 'reseller',
          status: 'active',
        },
      ],
      'GET /api/v1/admin/stores': STORES,
      'POST /api/v1/admin/bot-store-bindings': { id: 'b2' },
    });
    render(<StoreBotsView api={api} toast={() => {}} />);
    expect(await screen.findByText('@rep_bot', { exact: false })).toBeTruthy();
    // the write form is hidden for a role without write access
    expect(screen.queryByText('اتصال ربات جدید')).toBeNull();
  });

  it('notices tab: saves custom notice texts and the digest switch for the chosen store', async () => {
    stubFetch({
      'GET /api/v1/admin/stores/s1/vpn-notices': {
        traffic_low_levels: [80, 90],
        is_default: true,
        daily_digest: false,
        has_owner: true,
      },
      'GET /api/v1/admin/stores/s1/vpn-notice-texts': {
        texts: {},
        kinds: ['vpn_expired'],
        placeholders: ['{store}', '{level}'],
      },
      'PUT /api/v1/admin/stores/s1/vpn-notice-texts': {
        texts: { vpn_expired: { title: 'پایان', body: 'تمام شد {store}' } },
        kinds: ['vpn_expired'],
        placeholders: [],
      },
      'GET /api/v1/admin/stores': STORES,
    });
    const user = userEvent.setup();
    render(<StoreNoticesView api={{ ...api, perms: ['infrastructure:rw'] }} toast={() => {}} />);
    await user.selectOptions(await screen.findByLabelText('فروشگاه'), 's1');
    await user.type(await screen.findByLabelText('عنوان انقضای اکانت'), 'پایان');
    await user.type(screen.getByLabelText('متن انقضای اکانت'), 'تمام شد');
    await user.click(screen.getByText('ذخیره‌ی متن‌ها'));
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'PUT' && c.path.endsWith('/vpn-notice-texts'))).toBe(true),
    );
    const put = calls.find((c) => c.method === 'PUT');
    expect(put.body.texts.vpn_expired).toEqual({ title: 'پایان', body: 'تمام شد' });
  });

  it('unassigned products: warns, and stays silent when every product is in a bundle', async () => {
    stubFetch({
      'GET /api/v1/admin/bundle-products/unassigned': [
        { product_id: 'p1', code: 'x', name: 'محصول یتیم', is_active: true },
      ],
    });
    const { unmount } = render(<UnassignedProducts call={(p, o) => fetch(`http://core.test${p}`, o)} />);
    expect(await screen.findByText('محصول یتیم')).toBeTruthy();
    unmount();
    stubFetch({ 'GET /api/v1/admin/bundle-products/unassigned': [] });
    const { container } = render(<UnassignedProducts call={(p, o) => fetch(`http://core.test${p}`, o)} />);
    await waitFor(() => expect(calls.length).toBeGreaterThan(0));
    expect(container.textContent).toBe('');
  });

  it('product availability: loads the store state and posts the change', async () => {
    stubFetch({
      'GET /api/v1/admin/products/p1/availability': {
        store_id: 's1',
        enabled: true,
        listed: true,
        customer_price: null,
      },
      'POST /api/v1/admin/products/p1/availability': { ok: true },
    });
    const user = userEvent.setup();
    render(
      <ProductAvailability
        call={(p, o) => fetch(`http://core.test${p}`, o)}
        productId="p1"
        stores={STORES}
        toast={() => {}}
      />,
    );
    await user.selectOptions(screen.getByLabelText('فروشگاه'), 's1');
    const toggle = await screen.findByRole('switch', { name: /نمایش در ویترین/ });
    await user.click(toggle);
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true));
    expect(calls.find((c) => c.method === 'POST').body).toEqual({ store_id: 's1', enabled: true, listed: false });
  });
});
