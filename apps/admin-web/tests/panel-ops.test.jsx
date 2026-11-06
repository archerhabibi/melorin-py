import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PanelOpsView from '../src/PanelOpsView.jsx';
import { DialogHost } from '../src/ui.jsx';

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
const panel = {
  id: 'p1',
  name: 'pg-main',
  kind: 'pasarguard',
  capabilities: {
    access: {
      level: 'owner',
      role: 'owner',
      warnings: [{ code: 'owner_credential', message: 'Melorin با حساب owner پنل وصل است', permissions: [] }],
    },
  },
};
const issue = {
  id: 'i1',
  kind: 'owner_mismatch',
  status: 'open',
  occurrences: 3,
  details: { expected: 'ml_main', panel: 'Ajdar' },
  username: 'alice',
  panel_name: 'pg-main',
  store_name: 'Main',
  last_seen_at: null,
  allowed_actions: ['resync', 'fix_owner', 'resolve', 'ignore'],
};

function mock(calls) {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, o = {}) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '');
    calls.push([o.method || 'GET', path, o.body]);
    if (path === '/api/v1/admin/stores') return json([{ id: 's1', name: 'Main Store' }]);
    if (path === '/api/v1/admin/stores/s1/vpn-notices') {
      if (o.method === 'PUT') {
        const levels = JSON.parse(o.body).traffic_low_levels;
        return json({ store_id: 's1', traffic_low_levels: levels, is_default: false, default_levels: [80, 90] });
      }
      if (o.method === 'DELETE')
        return json({ store_id: 's1', traffic_low_levels: [80, 90], is_default: true, default_levels: [80, 90] });
      return json({ store_id: 's1', traffic_low_levels: [80, 90], is_default: true, default_levels: [80, 90] });
    }
    if (path.startsWith('/api/v1/admin/panels/p1/nodes')) {
      return json({
        panel_id: 'p1',
        health_status: 'degraded',
        detail: { reason: '1 از 2 نود فعال خطا دارد', sellable: true },
        nodes: [
          { remote_id: 1, name: 'ok-node', status: 'connected' },
          {
            remote_id: 2,
            name: 'bad-node',
            status: 'error',
            message: 'CERTIFICATE_VERIFY_FAILED',
            hint: 'server_ca را تنظیم کنید',
          },
        ],
      });
    }
    if (path.startsWith('/api/v1/admin/panels')) return json([panel]);
    if (path.startsWith('/api/v1/admin/reconciliation/summary'))
      return json({ open: { owner_mismatch: 1 }, open_total: 1, orphans_open: 1 });
    if (path.startsWith('/api/v1/admin/reconciliation/issues/i1/action')) return json({ ...issue, status: 'resolved' });
    if (path.startsWith('/api/v1/admin/reconciliation/issues')) return json({ total: 1, items: [issue] });
    if (path.startsWith('/api/v1/admin/panel-orphans')) return json({ total: 0, items: [] });
    return json({}, 404);
  });
}

describe('PanelOpsView', () => {
  it('lists issues with only the actions the API allows, and runs an action after confirmation', async () => {
    const calls = [];
    mock(calls);
    render(
      <>
        <PanelOpsView api={{ base: 'http://core.test' }} toast={vi.fn()} />
        <DialogHost />
      </>,
    );
    expect(await screen.findByText('alice', { exact: false })).toBeTruthy();
    await userEvent.click(await screen.findByRole('button', { name: /اصلاح مالک روی پنل/ }));
    await userEvent.click(await screen.findByRole('button', { name: 'تأیید' }));
    await waitFor(() => expect(calls.some((c) => c[0] === 'POST' && c[1].endsWith('/issues/i1/action'))).toBe(true));
    const post = calls.find((c) => c[0] === 'POST');
    expect(JSON.parse(post[2])).toMatchObject({ action: 'fix_owner' });
  });

  it('shows the access warning and the failing node with its fix hint once a panel is chosen', async () => {
    const calls = [];
    mock(calls);
    render(<PanelOpsView api={{ base: 'http://core.test' }} toast={vi.fn()} />);
    await screen.findByRole('option', { name: 'pg-main' });
    await userEvent.selectOptions(screen.getByLabelText('پنل'), 'p1');
    expect(await screen.findByText(/Melorin با حساب owner پنل وصل است/)).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: 'نودها' }));
    expect(await screen.findByText('bad-node')).toBeTruthy();
    expect(screen.getByText(/server_ca را تنظیم کنید/)).toBeTruthy();
    expect(screen.getByText(/1 از 2 نود فعال خطا دارد/)).toBeTruthy();
  });

  it('saves a store-specific low-traffic list, refuses a bad one without calling the API, and can reset', async () => {
    const calls = [];
    const toast = vi.fn();
    mock(calls);
    render(<PanelOpsView api={{ base: 'http://core.test' }} toast={toast} />);
    await userEvent.click(await screen.findByRole('button', { name: /هشدار حجم/ }));
    await screen.findByRole('option', { name: 'Main Store' });
    await userEvent.selectOptions(screen.getByLabelText('فروشگاه'), 's1');
    const input = await screen.findByLabelText('درصدهای هشدار');
    expect(input.value).toBe('80, 90');

    await userEvent.clear(input);
    await userEvent.type(input, '0, 120');
    await userEvent.click(screen.getByRole('button', { name: 'ذخیره' }));
    expect(toast).toHaveBeenCalledWith(expect.stringContaining('۹۹'));
    expect(calls.some((c) => c[0] === 'PUT')).toBe(false);

    await userEvent.clear(input);
    await userEvent.type(input, '50, 75');
    await userEvent.click(screen.getByRole('button', { name: 'ذخیره' }));
    await waitFor(() => expect(calls.some((c) => c[0] === 'PUT')).toBe(true));
    expect(JSON.parse(calls.find((c) => c[0] === 'PUT')[2])).toEqual({ traffic_low_levels: [50, 75] });

    await userEvent.click(await screen.findByRole('button', { name: 'بازگشت به پیش‌فرض' }));
    await waitFor(() => expect(calls.some((c) => c[0] === 'DELETE')).toBe(true));
    await waitFor(() => expect(screen.getByLabelText('درصدهای هشدار').value).toBe('80, 90'));
  });
});
