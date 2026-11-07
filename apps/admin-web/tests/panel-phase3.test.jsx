import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PanelCapacityTab from '../src/PanelCapacityTab.jsx';
import PanelTemplatesTab from '../src/PanelTemplatesTab.jsx';
import AccountToolsPanel from '../src/AccountToolsPanel.jsx';
import { DialogHost } from '../src/ui.jsx';

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
const mk = (handler) => {
  const calls = [];
  const call = async (path, o = {}) => {
    calls.push([o.method || 'GET', path, o.body]);
    return handler(path, o);
  };
  return { call, calls };
};

afterEach(() => vi.restoreAllMocks());

describe('PanelCapacityTab (PG-08)', () => {
  const capacity = {
    panel_id: 'p1',
    capacity_ops: true,
    groups: {
      2: { status: 'blocked', score: 0, reasons: ['هیچ نود متصلی ندارد'], hosts: 3, nodes: 0, total_users: 4 },
    },
    servers: [
      {
        id: 's1',
        name: 'srv-a',
        enabled: true,
        sellable: false,
        sellable_reason: 'نود متصلی برای این مقصد نیست',
        checked_at: null,
        capacity_info: {
          capacity: 50,
          melorin_accounts: 2,
          panel_users: 5,
          outside_melorin: 3,
          source: 'max',
          used: 5,
          percent: 10,
          state: 'ok',
        },
      },
    ],
  };

  it('shows sellability, outside-Melorin users and group reasons', async () => {
    const { call } = mk(() => json(capacity));
    render(<PanelCapacityTab call={call} panelId="p1" toast={() => {}} />);
    expect(await screen.findByText('srv-a')).toBeInTheDocument();
    expect(screen.getByText('فروش متوقف')).toBeInTheDocument();
    expect(screen.getByText('نود متصلی برای این مقصد نیست')).toBeInTheDocument();
    expect(screen.getByText(/خارج از Melorin: 3/)).toBeInTheDocument();
    expect(screen.getByText('هیچ نود متصلی ندارد')).toBeInTheDocument();
  });

  it('refresh posts and reloads', async () => {
    const { call, calls } = mk((path, o) =>
      o.method === 'POST' ? json({ changes: [{ server: 'srv-a', kind: 'blocked', to: 'x' }] }) : json(capacity),
    );
    render(<PanelCapacityTab call={call} panelId="p1" toast={() => {}} />);
    await userEvent.click(await screen.findByRole('button', { name: /بررسی همین حالا/ }));
    await waitFor(() => expect(calls.some(([m, p]) => m === 'POST' && p.endsWith('/capacity/refresh'))).toBe(true));
  });

  it('explains an unsupported panel', async () => {
    const { call } = mk(() => json({ ...capacity, capacity_ops: false }));
    render(<PanelCapacityTab call={call} panelId="p1" toast={() => {}} />);
    expect(await screen.findByText(/پشتیبانی نمی‌کند/)).toBeInTheDocument();
  });
});

describe('PanelTemplatesTab (PG-09)', () => {
  const overview = {
    supported: true,
    error: null,
    mappings: [
      {
        product_id: 'pr1',
        product_name: 'یک‌ماهه',
        remote_template_id: 7,
        name: 'mel-1m',
        managed: true,
        exists_on_panel: true,
        drift: { data_limit: { package: 10, panel: 5 } },
      },
    ],
    unmapped: [{ id: 9, name: 'old' }],
  };
  const products = [
    { id: 'pr1', name: 'یک‌ماهه' },
    { id: 'pr2', name: 'سه‌ماهه' },
  ];
  const handler = (path, o) => {
    if (path.endsWith('/products')) return json(products);
    if (o.method && o.method !== 'GET') return json({});
    return json(overview);
  };

  it('shows drift and syncs a managed template', async () => {
    const { call, calls } = mk(handler);
    render(<PanelTemplatesTab call={call} panelId="p1" toast={() => {}} />);
    expect(await screen.findByText(/اختلاف — حجم/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /همگام‌سازی با پکیج/ }));
    await waitFor(() => expect(calls.some(([m, p]) => m === 'POST' && p.endsWith('/templates/pr1/sync'))).toBe(true));
  });

  it('creates a template only for a package that has none', async () => {
    const { call, calls } = mk(handler);
    render(<PanelTemplatesTab call={call} panelId="p1" toast={() => {}} />);
    const select = await screen.findByLabelText('پکیج');
    expect(Array.from(select.options).map((o) => o.value)).not.toContain('pr1');
    await userEvent.selectOptions(select, 'pr2');
    await userEvent.click(screen.getByRole('button', { name: /ساخت تمپلیت/ }));
    await waitFor(() => {
      const c = calls.find(([m, p]) => m === 'POST' && p.endsWith('/panels/p1/templates'));
      expect(JSON.parse(c[2])).toEqual({ product_id: 'pr2' });
    });
  });

  it('links an unmapped template to the chosen package', async () => {
    const { call, calls } = mk(handler);
    render(<PanelTemplatesTab call={call} panelId="p1" toast={() => {}} />);
    await userEvent.selectOptions(await screen.findByLabelText('پکیج'), 'pr2');
    await userEvent.click(screen.getByRole('button', { name: /وصل به #9/ }));
    await waitFor(() => {
      const c = calls.find(([m, p]) => m === 'POST' && p.endsWith('/templates/link'));
      expect(JSON.parse(c[2])).toEqual({ product_id: 'pr2', remote_template_id: 9 });
    });
  });
});

describe('AccountToolsPanel (PG-10)', () => {
  const matrix = [
    { tool: 'usage', label: 'نمودار مصرف', write: false, available: true, reason: null },
    { tool: 'presence', label: 'آخرین اتصال', write: false, available: true, reason: null },
    { tool: 'devices', label: 'دستگاه‌ها', write: false, available: true, reason: null },
    { tool: 'devices_manage', label: 'x', write: true, available: true, reason: null },
    { tool: 'rotate', label: 'x', write: true, available: true, reason: null },
    { tool: 'suspend', label: 'x', write: true, available: true, reason: null },
    { tool: 'adjust', label: 'x', write: true, available: true, reason: null },
    { tool: 'change_plan', label: 'x', write: true, available: false, reason: 'پنل پشتیبانی نمی‌کند' },
  ];
  const handler = (path, o) => {
    if (path.endsWith('/products')) return json([{ id: 'pr1', name: 'یک‌ماهه' }]);
    if (o.method && o.method !== 'GET') return json({});
    if (path.endsWith('/tools')) return json(matrix);
    if (path.includes('/presence'))
      return json({ online_at: null, online_now: false, never_connected: true, lifetime_used_bytes: 0 });
    if (path.includes('/usage'))
      return json({ period: 'day', days: 30, points: [], by_node: [], total_bytes: 2 ** 30 });
    if (path.includes('/devices'))
      return json({ count: 1, items: [{ hwid: 'h1', label: 'Pixel', platform: 'android', last_seen: null }] });
    return json({});
  };

  it('renders presence, usage and devices, and disables a tool with its reason', async () => {
    const { call } = mk(handler);
    render(<AccountToolsPanel call={call} accountId="a1" toast={() => {}} />);
    expect(await screen.findByText(/هنوز هیچ اتصالی ثبت نشده/)).toBeInTheDocument();
    expect(screen.getByText(/Pixel/)).toBeInTheDocument();
    const change = screen.getByRole('button', { name: 'تغییر پلن' });
    expect(change).toBeDisabled();
    expect(change).toHaveAttribute('title', 'پنل پشتیبانی نمی‌کند');
  });

  it('rotating the link needs a confirmation and then posts', async () => {
    const { call, calls } = mk(handler);
    render(
      <>
        <DialogHost />
        <AccountToolsPanel call={call} accountId="a1" toast={() => {}} />
      </>,
    );
    await userEvent.click(await screen.findByRole('button', { name: /لینک اشتراک جدید/ }));
    expect(calls.some(([m, p]) => m === 'POST' && p.includes('rotate-subscription'))).toBe(false);
    await userEvent.click(await screen.findByRole('button', { name: 'تأیید' }));
    await waitFor(() =>
      expect(
        calls.some(([m, p]) => m === 'POST' && p === '/api/v1/admin/vpn-accounts/a1/tools/rotate-subscription'),
      ).toBe(true),
    );
  });
});
