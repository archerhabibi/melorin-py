import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import StorePricesView from '../src/StorePricesView.tsx';
import StoreApiView from '../src/StoreApiView.tsx';

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
const api = { base: 'http://core.test' };

describe('store hub: prices and API tabs', () => {
  it('prices tab shows the reseller price table read-only, with the cost floor and state', async () => {
    const calls = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url, o = {}) => {
        const path = String(url).replace('http://core.test', '');
        calls.push([o.method || 'GET', path]);
        if (path === '/api/v1/admin/resellers') return json([{ id: 's9', name: 'Acme', slug: 'acme' }]);
        if (path === '/api/v1/admin/stores/s9/reseller-prices')
          return json([
            {
              product_id: 'p1',
              name: 'Monthly',
              currency: 'IRT',
              customer_price: 90000,
              cost_floor: 70000,
              state: 'ok',
              bundles: [{ bundle_id: 'b1', bundle_name: 'Eco', cost: 70000, effective_price: 90000, state: 'ok' }],
            },
          ]);
        return json({}, 404);
      }),
    );
    render(<StorePricesView api={api} toast={vi.fn()} />);
    await screen.findByRole('option', { name: 'Acme' });
    await userEvent.selectOptions(screen.getByLabelText('فروشگاه نماینده'), 's9');
    expect(await screen.findByText('Monthly')).toBeTruthy();
    expect(screen.getByText('Eco')).toBeTruthy();
    expect(calls.every(([m]) => m === 'GET')).toBe(true);
  });

  it('API tab flips one store with PUT ?enabled= and reloads', async () => {
    const calls = [];
    let enabled = false;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url, o = {}) => {
        const path = String(url).replace('http://core.test', '');
        calls.push([o.method || 'GET', path]);
        if (path === '/api/v1/admin/resellers')
          return json([{ id: 's9', name: 'Acme', slug: 'acme', api_enabled: enabled }]);
        if (path.startsWith('/api/v1/admin/reseller-stores/s9/api')) {
          enabled = path.endsWith('enabled=true');
          return json({ store_id: 's9', api_enabled: enabled });
        }
        return json({}, 404);
      }),
    );
    const toast = vi.fn();
    render(<StoreApiView api={api} toast={toast} />);
    await userEvent.click(await screen.findByRole('switch', { name: /Acme/ }));
    await waitFor(() => expect(calls.some(([m, p]) => m === 'PUT' && p.endsWith('/api?enabled=true'))).toBe(true));
    await waitFor(() => expect(toast).toHaveBeenCalled());
  });
});
