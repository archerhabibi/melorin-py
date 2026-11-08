import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PanelOpsView from '../src/PanelOpsView.jsx';
import { DialogHost } from '../src/ui.jsx';

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
const panel = { id: 'p1', name: 'pg-main', kind: 'pasarguard', capabilities: {} };
const drift = (policy = 'keep', drifting = 1) => ({
  panel_id: 'p1',
  policy,
  policies: [
    { value: 'keep', label: 'پنل کاربر منقضی را پاک نکند' },
    { value: 'aligned', label: 'هم‌راستا با مهلت تمدید' },
  ],
  grace_days: 7,
  checked_at: '2026-11-08T10:00:00Z',
  drifting,
  findings: [
    { key: 'webhook', state: 'drift', message: 'رویداد در پنل خاموش شده است' },
    { key: 'hwid', state: 'info', message: 'محدودیت دستگاه (HWID) در پنل غیرفعال است.' },
  ],
  error: null,
});
const reading = {
  panel_id: 'p1',
  health_status: 'degraded',
  taken_at: new Date().toISOString(),
  fresh_minutes: 15,
  nodes: { connected: 1, connecting: 0, disabled: 2, error: 4 },
  reading: { up: true, latency_seconds: 0.21, online_users: 3, users: { active: 5 }, cpu_ratio: 0.5, mem_ratio: 0.95 },
};
const backups = (state = 'not_configured') => ({
  state,
  configured: state !== 'not_configured',
  last_success_at: null,
  age_seconds: null,
  max_age_hours: 36,
  runs: [],
});

function mock(calls, { backup = 'not_configured' } = {}) {
  let policy = 'keep';
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, o = {}) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '');
    calls.push([o.method || 'GET', path, o.body]);
    if (path === '/api/v1/admin/panels/p1/metrics') return json(reading);
    if (path === '/api/v1/admin/panels/p1/settings-drift/check') return json(drift(policy, 0));
    if (path === '/api/v1/admin/panels/p1/settings-drift') return json(drift(policy));
    if (path === '/api/v1/admin/panels/p1/lifecycle-policy') {
      policy = JSON.parse(o.body).policy;
      return json(drift(policy, 0));
    }
    if (path === '/api/v1/admin/panel-backups') return json(backups(backup));
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

const ui = (toast = vi.fn()) => (
  <>
    <PanelOpsView api={{ base: 'http://core.test' }} toast={toast} />
    <DialogHost />
  </>
);

afterEach(() => vi.restoreAllMocks());

describe('PanelPhase5Tab', () => {
  it('without a panel it shows only the global panel-backup status and asks to pick a panel', async () => {
    const calls = [];
    mock(calls);
    render(ui());
    await userEvent.click(await screen.findByRole('button', { name: 'شاخص و پشتیبان' }));
    expect(await screen.findByText('تنظیم نشده')).toBeTruthy();
    expect(screen.getByText(/یک پنل را از فهرست بالا انتخاب کنید/)).toBeTruthy();
    expect(calls.some((c) => c[1].includes('/metrics'))).toBe(false);
  });

  it('shows readings, drift findings and highlights a failing node count', async () => {
    mock([]);
    render(ui());
    await screen.findByRole('option', { name: 'pg-main' });
    await userEvent.selectOptions(screen.getByLabelText('پنل'), 'p1');
    await userEvent.click(screen.getByRole('button', { name: 'شاخص و پشتیبان' }));
    expect(await screen.findByText('در دسترس')).toBeTruthy();
    expect(screen.getByText('1 / 4')).toBeTruthy();
    expect(await screen.findByText('رویداد در پنل خاموش شده است')).toBeTruthy();
    expect(screen.getByText(/1 ناهمخوانی/)).toBeTruthy();
  });

  it('"check now" only reads (POST check) and the policy change needs a reason and is audited server-side', async () => {
    const calls = [];
    mock(calls);
    render(ui());
    await screen.findByRole('option', { name: 'pg-main' });
    await userEvent.selectOptions(screen.getByLabelText('پنل'), 'p1');
    await userEvent.click(screen.getByRole('button', { name: 'شاخص و پشتیبان' }));
    await userEvent.click(await screen.findByRole('button', { name: /بررسی اکنون/ }));
    await waitFor(() =>
      expect(calls.some((c) => c[0] === 'POST' && c[1].endsWith('/settings-drift/check'))).toBe(true),
    );
    expect(calls.some((c) => c[0] === 'PUT')).toBe(false);

    await userEvent.click(screen.getByRole('button', { name: 'هم‌راستا با مهلت تمدید' }));
    expect(calls.some((c) => c[1].endsWith('/lifecycle-policy'))).toBe(false); // nothing is sent before the reason is given
    await userEvent.type(await screen.findByRole('textbox'), 'پنل را خودم هم‌راستا کردم');
    await userEvent.click(screen.getByRole('button', { name: 'ثبت' }));
    await waitFor(() => expect(calls.some((c) => c[0] === 'PUT' && c[1].endsWith('/lifecycle-policy'))).toBe(true));
    expect(JSON.parse(calls.find((c) => c[0] === 'PUT')[2])).toEqual({
      policy: 'aligned',
      reason: 'پنل را خودم هم‌راستا کردم',
    });
  });

  it('flags a stale panel backup', async () => {
    mock([], { backup: 'stale' });
    render(ui());
    await userEvent.click(await screen.findByRole('button', { name: 'شاخص و پشتیبان' }));
    expect(await screen.findByText('قدیمی یا ناموفق')).toBeTruthy();
  });
});
