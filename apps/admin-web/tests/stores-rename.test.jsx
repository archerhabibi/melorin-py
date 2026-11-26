// ADR-R3: the operator names (and renames) the MAIN store; resellers keep their own edit route.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import StoresView from '../src/features/stores/StoresView.tsx';

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const api = { base: 'http://core.test' };

const store = (over) => ({
  currency: 'IRT',
  status: 'active',
  owner_user_id: null,
  domain: null,
  parent_store_id: null,
  bot_username: null,
  ...over,
});

function stubCore({ patch } = {}) {
  let main = store({ id: 's1', name: 'فروشگاه اصلی', slug: 'main', kind: 'main' });
  const reseller = store({ id: 's2', name: 'Tehran Net', slug: 'tehran', kind: 'reseller', parent_store_id: 's1' });
  const calls = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, o = {}) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '');
    const method = o.method || 'GET';
    calls.push([method, path, o.body]);
    if (path === '/api/v1/admin/stores' && method === 'GET') return json([main, reseller]);
    if (path === '/api/v1/admin/stores/main' && method === 'PATCH') {
      if (patch) return patch();
      main = { ...main, name: JSON.parse(o.body).name };
      return json(main);
    }
    return json([]);
  });
  return calls;
}

afterEach(() => vi.restoreAllMocks());

// 'فروشگاه اصلی' is also a KPI label and the kind badge of the row, so rows are opened by their unique slug / name.
const openStore = async (slugOrName) => {
  await userEvent.click(await screen.findByText(slugOrName));
  return screen.findByRole('dialog');
};

describe('main store name', () => {
  it('renames the main store from its drawer and shows the new name', async () => {
    const calls = stubCore();
    const toast = vi.fn();
    render(<StoresView api={api} toast={toast} />);
    const dlg = await openStore('main');

    const input = within(dlg).getByLabelText(/نام فروشگاه/);
    expect(input).toHaveValue('فروشگاه اصلی');
    const save = within(dlg).getByRole('button', { name: 'ذخیرهٔ نام' });
    expect(save).toBeDisabled(); // unchanged

    await userEvent.clear(input);
    expect(save).toBeDisabled(); // empty
    await userEvent.type(input, '  Paris   VPN ');
    await userEvent.click(save);

    await waitFor(() => expect(toast).toHaveBeenCalledWith('نام فروشگاه تغییر کرد'));
    const patch = calls.find(([m, p]) => m === 'PATCH' && p === '/api/v1/admin/stores/main');
    expect(JSON.parse(patch[2])).toEqual({ name: 'Paris VPN' }); // whitespace collapsed before it is sent
    expect((await screen.findAllByText('Paris VPN')).length).toBeGreaterThan(0); // the list reloaded
  });

  it('reports a refusal from Core and keeps the form', async () => {
    stubCore({
      patch: () => json({ error: { code: 'INVALID_STORE_NAME', message: 'نام فروشگاه نباید خالی باشد.' } }, 422),
    });
    const toast = vi.fn();
    render(<StoresView api={api} toast={toast} />);
    const dlg = await openStore('main');
    await userEvent.type(within(dlg).getByLabelText(/نام فروشگاه/), ' جدید');
    await userEvent.click(within(dlg).getByRole('button', { name: 'ذخیرهٔ نام' }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith('ناموفق: نام فروشگاه نباید خالی باشد.'));
    expect(within(dlg).getByRole('button', { name: 'ذخیرهٔ نام' })).toBeEnabled();
  });

  it("does not offer the form for a reseller's store (that name has its own edit route)", async () => {
    stubCore();
    render(<StoresView api={api} toast={vi.fn()} />);
    const dlg = await openStore('Tehran Net');
    expect(within(dlg).queryByRole('button', { name: 'ذخیرهٔ نام' })).toBeNull();
  });

  it('tells the operator that Melorin is the platform name, not a store name', async () => {
    stubCore();
    render(<StoresView api={api} toast={vi.fn()} />);
    const dlg = await openStore('main');
    expect(within(dlg).getByText(/«ملورین» نام پلتفرم است/)).toBeInTheDocument();
  });
});
