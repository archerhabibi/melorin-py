import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import BulkOperationsView from '../src/BulkOperationsView.tsx';
import StoreGovernanceView from '../src/StoreGovernanceView.tsx';
import { extraRoutes } from '../src/AdminExtra.tsx';

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
const PANELS = [
  { id: 'p1', name: 'پنل اصلی', kind: 'pasarguard' },
  { id: 'p2', name: 'پنل دیگر', kind: 'marzban' },
];
const STORES = [{ id: 's1', name: 'فروشگاه اصلی' }];

function mockFetch(handler) {
  const calls = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, o = {}) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '');
    calls.push([o.method || 'GET', path, o.body]);
    return handler(path, o) ?? json([]);
  });
  return calls;
}

describe('PG-11 bulk operations screen', () => {
  const plan = {
    id: 'op1',
    kind: 'extend_days',
    kind_label: 'جبران زمان',
    total: 42,
    skipped: 3,
    selection: { skipped: { expired: 3 } },
    sample: ['u1', 'u2'],
    expires_at: null,
  };
  const base = (path, o) => {
    if (path === '/api/v1/admin/panels') return json(PANELS);
    if (path === '/api/v1/admin/stores') return json(STORES);
    if (path.startsWith('/api/v1/admin/bulk-operations?')) return json({ total: 0, items: [] });
    if (path.endsWith('/preview')) return json(plan);
    if (path.endsWith('/confirm')) return json({ id: 'op1', status: 'confirmed' });
    return null;
  };

  it('is registered in the admin routes', () => {
    expect(Object.keys(extraRoutes)).toContain('عملیات گروهی'); // volume governance is a Store Hub tab now
  });

  it('offers only PasarGuard panels and requires a reason before previewing', async () => {
    mockFetch(base);
    render(<BulkOperationsView api={{ base: 'http://core.test' }} toast={vi.fn()} />);
    await screen.findByRole('option', { name: 'پنل اصلی' });
    expect(screen.queryByRole('option', { name: 'پنل دیگر' })).toBeNull();
    const btn = screen.getByRole('button', { name: /پیش‌نمایش/ });
    expect(btn).toBeDisabled();
    await userEvent.type(screen.getByPlaceholderText(/قطعی نود/), 'جبران قطعی');
    expect(btn).toBeEnabled();
  });

  it('previews, blocks confirm until the exact count is typed, then confirms with that count', async () => {
    const calls = mockFetch(base);
    const toast = vi.fn();
    render(<BulkOperationsView api={{ base: 'http://core.test' }} toast={toast} />);
    await screen.findByRole('option', { name: 'پنل اصلی' });
    await userEvent.type(screen.getByPlaceholderText(/قطعی نود/), 'جبران قطعی');
    await userEvent.click(screen.getByRole('button', { name: /پیش‌نمایش/ }));
    const confirm = await screen.findByRole('button', { name: /تأیید و اجرا/ });
    expect(confirm).toBeDisabled();
    const input = screen.getByPlaceholderText(/برای تأیید/);
    await userEvent.type(input, '41');
    expect(confirm).toBeDisabled();
    await userEvent.clear(input);
    await userEvent.type(input, '42');
    expect(confirm).toBeEnabled();
    await userEvent.click(confirm);
    await waitFor(() => expect(toast).toHaveBeenCalledWith('در صف اجرا قرار گرفت'));
    const post = calls.find(([, p]) => p.endsWith('/op1/confirm'));
    expect(JSON.parse(post[2])).toEqual({ count: 42 });
    const prev = calls.find(([, p]) => p.endsWith('/preview'));
    expect(JSON.parse(prev[2])).toMatchObject({
      kind: 'extend_days',
      params: { days: 3 },
      selection: { panel_id: 'p1' },
    });
  });

  it('says so when nothing matches the selection', async () => {
    mockFetch((path) =>
      path.endsWith('/preview') ? json({ error: { code: 'BULK_EMPTY', message: 'x' } }, 422) : base(path),
    );
    const toast = vi.fn();
    render(<BulkOperationsView api={{ base: 'http://core.test' }} toast={toast} />);
    await screen.findByRole('option', { name: 'پنل اصلی' });
    await userEvent.type(screen.getByPlaceholderText(/قطعی نود/), 'جبران قطعی');
    await userEvent.click(screen.getByRole('button', { name: /پیش‌نمایش/ }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith('هیچ اکانت مناسبی پیدا نشد'));
  });

  it('offers resume only for partial or failed operations', async () => {
    const op = (id, status) => ({
      id,
      status,
      kind_label: 'k',
      panel_name: 'p',
      total: 5,
      succeeded: 3,
      failed: 2,
      skipped: 0,
      reason: 'r',
      created_at: null,
    });
    mockFetch((path) =>
      path.startsWith('/api/v1/admin/bulk-operations?')
        ? json({ total: 2, items: [op('a', 'partial'), op('b', 'done')] })
        : base(path),
    );
    render(<BulkOperationsView api={{ base: 'http://core.test' }} toast={vi.fn()} />);
    await screen.findByText('ناقص');
    expect(screen.getAllByRole('button', { name: 'ازسرگیری' })).toHaveLength(1);
  });
});

describe('PG-12 store governance screen', () => {
  it('lists store admins and refreshes them from the panel', async () => {
    const calls = mockFetch((path, o) => {
      if (path === '/api/v1/admin/store-admins/refresh' && o.method === 'POST') return json({ updated: 2, errors: 0 });
      if (path === '/api/v1/admin/store-admins') return json({ items: [] });
      return null;
    });
    const toast = vi.fn();
    render(<StoreGovernanceView api={{ base: 'http://core.test' }} toast={toast} />);
    await waitFor(() => expect(calls.some(([, p]) => p === '/api/v1/admin/store-admins')).toBe(true));
    const refresh = screen.getAllByRole('button').find((b) => /خواندن مصرف/.test(b.textContent));
    await userEvent.click(refresh);
    await waitFor(() => expect(toast).toHaveBeenCalledWith('2 ادمین به‌روز شد'));
  });
});
