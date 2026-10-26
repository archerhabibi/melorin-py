import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import OrdersView from '../src/OrdersView.jsx';
import VpnAccountsView from '../src/VpnAccountsView.jsx';
import UsersView from '../src/UsersView.jsx';
import StoresView from '../src/StoresView.jsx';
import AuditView from '../src/AuditView.jsx';
import { DialogHost } from '../src/ui.jsx';
import { csvCell, fmtBytes, matches, relTime } from '../src/dataKit.jsx';

const json = (body, status = 200, headers = {}) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } });
const api = { base: 'http://core.test' };

const USERS = [
  {
    id: 'u1',
    email: 'ali@example.com',
    display_name: 'علی رضایی',
    is_active: true,
    is_super_admin: true,
    created_at: '2026-01-02T10:00:00Z',
  },
  {
    id: 'u2',
    email: 'sara@example.com',
    display_name: null,
    is_active: false,
    is_super_admin: false,
    created_at: '2026-02-03T10:00:00Z',
  },
];
const STORES = [
  {
    id: 's1',
    name: 'ملورین',
    slug: 'melorin',
    kind: 'main',
    status: 'active',
    currency: 'IRT',
    owner_user_id: 'u1',
    domain: 'melorin.example',
    parent_store_id: null,
    bot_username: 'melorin_bot',
  },
  {
    id: 's2',
    name: 'نماینده الف',
    slug: 'rep-a',
    kind: 'reseller',
    status: 'suspended',
    currency: 'IRT',
    owner_user_id: 'u2',
    domain: null,
    parent_store_id: 's1',
    bot_username: null,
  },
];
const ORDERS = [
  {
    id: 'o1',
    number: 'ORD-1001',
    user_id: 'u1',
    store_id: 's1',
    status: 'completed',
    total: 150000,
    currency: 'IRT',
    needs_review: false,
    created_at: '2026-03-01T10:00:00Z',
  },
  {
    id: 'o2',
    number: 'ORD-1002',
    user_id: 'u2',
    store_id: 's2',
    status: 'provisioning_failed',
    total: 90000,
    currency: 'IRT',
    needs_review: true,
    created_at: '2026-03-02T10:00:00Z',
  },
  {
    id: 'o3',
    number: 'ORD-1003',
    user_id: 'u1',
    store_id: 's1',
    status: 'refunded',
    total: 50000,
    currency: 'IRT',
    needs_review: false,
    created_at: '2026-03-03T10:00:00Z',
  },
];

function mockFetch(extra = {}) {
  const calls = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, o = {}) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '');
    calls.push([o.method || 'GET', path, o.body]);
    if (extra[path.split('?')[0]]) return extra[path.split('?')[0]](path, o);
    if (path.startsWith('/api/v1/admin/users')) return json(USERS);
    if (path.startsWith('/api/v1/admin/stores')) return json(STORES);
    if (path.startsWith('/api/v1/admin/orders') && (o.method || 'GET') === 'GET') return json(ORDERS);
    if (path.startsWith('/api/v1/admin/audit')) return json([]);
    return json({ ok: true });
  });
  return calls;
}

afterEach(() => vi.restoreAllMocks());

describe('dataKit helpers', () => {
  it('formats bytes in Persian units', () => {
    expect(fmtBytes(0)).toContain('بایت');
    expect(fmtBytes(5 * 1024 ** 3)).toContain('گیگابایت');
  });
  it('neutralises spreadsheet formulas in CSV cells and escapes quotes', () => {
    expect(csvCell('=SUM(A1)')).toBe(`"'=SUM(A1)"`);
    expect(csvCell('@x')).toBe(`"'@x"`);
    expect(csvCell('a"b')).toBe('"a""b"');
    expect(csvCell(null)).toBe('""');
  });
  it('matches ignoring case and Persian digits', () => {
    expect(matches('۱۰۰۱', 'ORD-1001')).toBe(true);
    expect(matches('SARA', 'sara@example.com')).toBe(true);
    expect(matches('zzz', 'abc', null)).toBe(false);
    expect(matches('', 'anything')).toBe(true);
  });
  it('returns an empty string for an unparsable date', () => {
    expect(relTime('not-a-date')).toBe('');
  });
});

describe('orders screen', () => {
  it('shows customer and store names instead of raw ids and filters by KPI', async () => {
    mockFetch();
    render(<OrdersView api={api} toast={vi.fn()} />);
    expect(await screen.findByText('ORD-1001')).toBeInTheDocument();
    expect(screen.getAllByText('علی رضایی').length).toBeGreaterThan(0);
    expect(screen.getAllByText('نماینده الف').length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole('button', { name: /نیازمند توجه/ }));
    expect(screen.getByText('ORD-1002')).toBeInTheDocument();
    expect(screen.queryByText('ORD-1001')).not.toBeInTheDocument();
  });

  it('searches by order number', async () => {
    mockFetch();
    render(<OrdersView api={api} toast={vi.fn()} />);
    await screen.findByText('ORD-1001');
    await userEvent.type(screen.getByLabelText('جستجوی سفارش'), '1003');
    expect(screen.getByText('ORD-1003')).toBeInTheDocument();
    expect(screen.queryByText('ORD-1001')).not.toBeInTheDocument();
  });

  it('offers only the actions the state machine allows', async () => {
    mockFetch();
    render(<OrdersView api={api} toast={vi.fn()} />);
    await userEvent.click(await screen.findByText('ORD-1002')); // provisioning_failed
    let dlg = await screen.findByRole('dialog');
    expect(within(dlg).getByRole('button', { name: /تلاش مجدد/ })).toBeInTheDocument();
    expect(within(dlg).getByRole('button', { name: /بررسی دستی/ })).toBeInTheDocument();
    expect(within(dlg).getByRole('button', { name: /استرداد/ })).toBeInTheDocument();
    await userEvent.click(within(dlg).getByRole('button', { name: 'بستن' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    await userEvent.click(screen.getByText('ORD-1003')); // refunded → nothing allowed
    dlg = await screen.findByRole('dialog');
    expect(within(dlg).queryByRole('button', { name: /تلاش مجدد/ })).not.toBeInTheDocument();
    expect(within(dlg).queryByRole('button', { name: /استرداد/ })).not.toBeInTheDocument();
    expect(within(dlg).getByText(/اقدام دستی برای این سفارش مجاز نیست/)).toBeInTheDocument();
  });

  it('retry posts to the retry endpoint and reports success', async () => {
    const calls = mockFetch();
    const toast = vi.fn();
    render(
      <>
        <OrdersView api={api} toast={toast} />
        <DialogHost />
      </>,
    );
    await userEvent.click(await screen.findByText('ORD-1002'));
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: /تلاش مجدد/ }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith('تلاش مجدد ثبت شد'));
    expect(calls.some(([m, p]) => m === 'POST' && p === '/api/v1/admin/orders/o2/retry')).toBe(true);
  });

  it('shows the server message when an action is refused', async () => {
    mockFetch({
      '/api/v1/admin/orders/o2/retry': () => json({ error: { message: 'این سفارش قابل تلاش مجدد نیست.' } }, 409),
    });
    const toast = vi.fn();
    render(<OrdersView api={api} toast={toast} />);
    await userEvent.click(await screen.findByText('ORD-1002'));
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: /تلاش مجدد/ }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith('این سفارش قابل تلاش مجدد نیست.'));
  });
});

describe('VPN accounts screen', () => {
  const ACC = (n, over = {}) => ({
    id: `a${n}`,
    user_id: 'u1',
    customer_name: 'علی رضایی',
    store_id: 's1',
    username: `acct-${n}`,
    status: 'active',
    health: 'active',
    days_left: 20,
    expires_at: '2026-12-01T00:00:00Z',
    traffic_limit_bytes: 10 * 1024 ** 3,
    traffic_used_bytes: 2 * 1024 ** 3,
    ...over,
  });

  it('queries the server with q/state and reads the total from X-Total-Count', async () => {
    const calls = mockFetch({
      '/api/v1/admin/vpn-accounts': (path) =>
        json(
          path.includes('limit=1&') || path.endsWith('limit=1')
            ? []
            : [ACC(1), ACC(2, { health: 'expiring', days_left: 2 })],
          200,
          {
            'X-Total-Count': '42',
          },
        ),
    });
    render(<VpnAccountsView api={api} toast={vi.fn()} />);
    expect(await screen.findByText('acct-1')).toBeInTheDocument();
    expect(screen.getByText('در آستانه انقضا', { selector: '.badge' })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('جستجوی اکانت'), 'ali');
    await waitFor(() => expect(calls.some(([, p]) => p.includes('q=ali') && p.includes('limit=20'))).toBe(true));
    await userEvent.click(screen.getByRole('button', { name: /منقضی$/ }));
    await waitFor(() =>
      expect(calls.some(([, p]) => p.includes('state=expired') && p.includes('limit=20'))).toBe(true),
    );
  });

  it('shows an unlimited account without a usage bar', async () => {
    mockFetch({
      '/api/v1/admin/vpn-accounts': () =>
        json([ACC(1, { traffic_limit_bytes: 0, days_left: null, expires_at: null })], 200, { 'X-Total-Count': '1' }),
    });
    render(<VpnAccountsView api={api} toast={vi.fn()} />);
    expect(await screen.findByText('acct-1')).toBeInTheDocument();
    expect(screen.getAllByText('نامحدود').length).toBeGreaterThan(0);
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });
});

describe('users screen', () => {
  it('filters inactive users and shows the stores a user owns', async () => {
    mockFetch();
    render(<UsersView api={api} />);
    expect(await screen.findByText('علی رضایی')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /غیرفعال/ }));
    expect(screen.queryByText('علی رضایی')).not.toBeInTheDocument();
    await userEvent.click(screen.getByText('sara@example.com'));
    const dlg = await screen.findByRole('dialog');
    expect(within(dlg).getByText('نماینده الف')).toBeInTheDocument();
  });
});

describe('stores screen', () => {
  it('filters resellers, resolves the owner and switches to card view', async () => {
    mockFetch();
    render(<StoresView api={api} />);
    expect(await screen.findByText('ملورین')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /نمایندگان/ }));
    expect(screen.queryByText('ملورین')).not.toBeInTheDocument();
    expect(screen.getByText('نماینده الف')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'کارت' }));
    expect(screen.getByText('نماینده الف')).toBeInTheDocument();
  });
});

describe('audit screen', () => {
  const EV = [
    {
      id: 'e1',
      actor_id: 'u1',
      action: 'order.refunded',
      entity_type: 'order',
      entity_id: 'o1',
      store_id: 's1',
      data: { reason: 'x', bot_token: 'SECRET123' },
      ip: '1.2.3.4',
      created_at: new Date().toISOString(),
    },
    {
      id: 'e2',
      actor_id: null,
      action: 'panel.created',
      entity_type: 'panel',
      entity_id: 'p1',
      store_id: null,
      data: {},
      ip: null,
      created_at: '2026-01-01T00:00:00Z',
    },
  ];
  it('labels events in Persian, resolves actors and redacts secrets in the payload', async () => {
    mockFetch({ '/api/v1/admin/audit': () => json(EV) });
    render(<AuditView api={api} />);
    expect(await screen.findByText('سفارش · مسترد شد')).toBeInTheDocument();
    expect(screen.getByText('سیستم')).toBeInTheDocument();
    await userEvent.click(screen.getByText('سفارش · مسترد شد'));
    const dlg = await screen.findByRole('dialog');
    expect(within(dlg).getByText(/عملیات حساس/)).toBeInTheDocument();
    expect(dlg.textContent).not.toContain('SECRET123');
    expect(dlg.textContent).toContain('••••••');
  });
  it('filters to sensitive operations only', async () => {
    mockFetch({ '/api/v1/admin/audit': () => json(EV) });
    render(<AuditView api={api} />);
    await screen.findByText('سفارش · مسترد شد');
    await userEvent.click(screen.getByRole('button', { name: /عملیات حساس/ }));
    expect(screen.queryByText('پنل · ایجاد شد')).not.toBeInTheDocument();
    expect(screen.getByText('سفارش · مسترد شد')).toBeInTheDocument();
  });
});
