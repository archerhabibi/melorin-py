import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PanelOpsView from '../src/PanelOpsView.jsx';
import { DialogHost } from '../src/ui.jsx';

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
const panel = { id: 'p1', name: 'pg-main', kind: 'pasarguard', capabilities: {} };
const base = {
  panel_id: 'p1',
  supported: true,
  url: 'https://melorin.test/api/v1/webhooks/pasarguard/p1',
  connected_at: null,
  last_event_at: null,
  silent_for_seconds: null,
  warnings: [],
  panel_side: null,
  counts: { pending: 0, processing: 0, processed: 1, ignored: 0, failed: 1, last_24h: 2 },
};
const eventsList = {
  total: 2,
  items: [
    {
      id: 'e1',
      action: 'user_limited',
      username: 'alice',
      status: 'processed',
      attempts: 0,
      outcome: 'active->limited',
      received_at: null,
    },
    {
      id: 'e2',
      action: 'user_expired',
      username: 'bob',
      status: 'failed',
      attempts: 5,
      outcome: 'panel error',
      received_at: null,
    },
  ],
};

function mock(calls, { connected = false, pageTotal = null } = {}) {
  let isConnected = connected;
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, o = {}) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '');
    calls.push([o.method || 'GET', path, o.body]);
    if (path === '/api/v1/admin/panels/p1/events/connect') {
      isConnected = true;
      return json({ ...base, connected: true, connected_at: '2026-11-07T10:00:00Z', warnings: [] });
    }
    if (path === '/api/v1/admin/panels/p1/events/disconnect') {
      isConnected = false;
      return json({ ...base, connected: false });
    }
    if (path === '/api/v1/admin/panels/p1/events/retry-failed') return json({ requeued: 1 });
    if (path.startsWith('/api/v1/admin/panels/p1/events/status'))
      return json({ ...base, connected: isConnected, silent_for_seconds: isConnected ? 8 * 3600 : null });
    if (path.startsWith('/api/v1/admin/panels/p1/events')) {
      if (pageTotal) {
        const offset = Number(new URL(`http://x${path}`).searchParams.get('offset') || 0);
        const n = Math.min(50, pageTotal - offset);
        return json({
          total: pageTotal,
          items: Array.from({ length: n }, (_, i) => ({
            id: `m${offset + i}`,
            action: 'user_updated',
            username: `u${offset + i}`,
            status: 'processed',
            attempts: 0,
            received_at: null,
          })),
        });
      }
      return json(eventsList);
    }
    if (path.startsWith('/api/v1/admin/panels/p1/nodes'))
      return json({ panel_id: 'p1', health_status: 'healthy', detail: {}, nodes: [] });
    if (path.startsWith('/api/v1/admin/stores')) return json([]);
    if (path.startsWith('/api/v1/admin/panels')) return json([panel]);
    if (path.startsWith('/api/v1/admin/reconciliation/summary'))
      return json({ open: {}, open_total: 0, orphans_open: 0 });
    if (path.startsWith('/api/v1/admin/reconciliation/issues')) return json({ total: 0, items: [] });
    if (path.startsWith('/api/v1/admin/panel-orphans')) return json({ total: 0, items: [] });
    return json({}, 404);
  });
}

async function openTab() {
  await screen.findByRole('option', { name: 'pg-main' });
  await userEvent.selectOptions(screen.getByLabelText('پنل'), 'p1');
  await userEvent.click(screen.getByRole('button', { name: 'رویدادهای زنده' }));
}

afterEach(() => vi.restoreAllMocks());

describe('PanelEventsTab', () => {
  it('asks to choose a panel first', async () => {
    mock([]);
    render(<PanelOpsView api={{ base: 'http://core.test' }} toast={vi.fn()} />);
    await userEvent.click(await screen.findByRole('button', { name: 'رویدادهای زنده' }));
    expect(screen.getByText(/یک پنل انتخاب کنید/, { selector: 'p' })).toBeTruthy();
  });

  it('connects only after confirmation and sends confirm=true; the secret is never part of any response shown', async () => {
    const calls = [];
    const toast = vi.fn();
    mock(calls);
    render(
      <>
        <PanelOpsView api={{ base: 'http://core.test' }} toast={toast} />
        <DialogHost />
      </>,
    );
    await openTab();
    expect(await screen.findByText('رویدادهای زنده وصل نیست')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: /^اتصال/ }));
    expect(calls.some((c) => c[1].endsWith('/events/connect'))).toBe(false);
    await userEvent.click(await screen.findByRole('button', { name: 'تأیید' }));
    await waitFor(() => expect(calls.some((c) => c[0] === 'POST' && c[1].endsWith('/events/connect'))).toBe(true));
    expect(JSON.parse(calls.find((c) => c[1].endsWith('/events/connect'))[2])).toEqual({
      confirm: true,
      rotate_secret: false,
    });
    expect(await screen.findByText('رویدادهای زنده وصل است')).toBeTruthy();
  });

  it('lists events, warns when a connected panel has been silent, and requeues failed events', async () => {
    const calls = [];
    mock(calls, { connected: true });
    render(<PanelOpsView api={{ base: 'http://core.test' }} toast={vi.fn()} />);
    await openTab();
    expect(await screen.findByText('اتمام حجم')).toBeTruthy();
    expect(screen.getByText('انقضا')).toBeTruthy();
    expect(screen.getByText(/چند ساعت است رویدادی نرسیده/)).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: 'تلاش مجدد ناموفق‌ها' }));
    await waitFor(() => expect(calls.some((c) => c[0] === 'POST' && c[1].endsWith('/events/retry-failed'))).toBe(true));
  });

  it('changing the filter refetches in place: the controls stay mounted and the status filter reaches the API', async () => {
    const calls = [];
    mock(calls, { connected: true });
    render(<PanelOpsView api={{ base: 'http://core.test' }} toast={vi.fn()} />);
    await openTab();
    const select = await screen.findByLabelText('وضعیت رویداد');
    await userEvent.selectOptions(select, 'failed');
    await waitFor(() =>
      expect(calls.some((c) => c[1].includes('/events?') && c[1].includes('status=failed'))).toBe(true),
    );
    expect(screen.getByLabelText('وضعیت رویداد')).toBe(select); // same node: not replaced by the loading spinner
  });

  it('pages through long lists and filters by username', async () => {
    const calls = [];
    mock(calls, { connected: true, pageTotal: 120 });
    render(<PanelOpsView api={{ base: 'http://core.test' }} toast={vi.fn()} />);
    await openTab();
    await userEvent.click(await screen.findByRole('button', { name: /نمایش بیشتر \(50 از 120\)/ }));
    await waitFor(() => expect(calls.some((c) => c[1].includes('offset=50'))).toBe(true));
    expect(await screen.findByText(/نمایش بیشتر \(100 از 120\)/)).toBeTruthy();
    await userEvent.type(screen.getByLabelText('نام کاربری'), 'alice');
    await waitFor(() => expect(calls.some((c) => c[1].includes('username=alice'))).toBe(true));
  });
});
