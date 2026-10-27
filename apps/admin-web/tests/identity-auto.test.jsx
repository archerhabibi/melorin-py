import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import IdentityAutoView from '../src/IdentityAutoView.jsx';
import { DialogHost } from '../src/ui.jsx';

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
const device = (over = {}) => ({
  id: 'd1',
  status: 'active',
  user: { id: 'u1', display_name: 'Ali', email: 'ali@example.com' },
  store_id: 's1',
  store_name: 'Main',
  telegram_id: 4242,
  label: 'Chrome · Windows',
  last_ip: '203.0.113.7',
  uses: 3,
  last_seen_at: '2026-10-27T10:00:00Z',
  expires_at: '2026-12-27T10:00:00Z',
  revoked_at: null,
  ...over,
});

function setup({ devices = [device()], merges = [] } = {}) {
  const calls = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, o = {}) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '');
    calls.push([o.method || 'GET', path, o.body]);
    if (path.includes('/trusted-devices/summary'))
      return json({ active_devices: 5, accounts: 4, revoked_devices: 2, auto_merges_30d: 1 });
    if (o.method === 'POST') return json({ ok: true, revoked: 1 });
    if (path.includes('/trusted-devices')) return json(devices);
    if (path.includes('/identity-auto-merges')) return json(merges);
    return json([]);
  });
  const toast = vi.fn();
  render(
    <>
      <IdentityAutoView api={{ base: 'http://core.test' }} toast={toast} />
      <DialogHost />
    </>,
  );
  return { calls, toast };
}

describe('admin «هویت خودکار»', () => {
  it('lists trusted devices with owner, store and browser, and shows the summary counters', async () => {
    setup();
    expect(await screen.findByText('Chrome · Windows')).toBeInTheDocument();
    expect(screen.getByText(/ali@example.com/)).toBeInTheDocument();
    expect(screen.getByText('Main')).toBeInTheDocument();
    expect(await screen.findByText('دستگاه فعال')).toBeInTheDocument();
  });

  it('revokes one device only after confirmation', async () => {
    const { calls, toast } = setup();
    await userEvent.click(await screen.findByRole('button', { name: /لغو اعتماد/ }));
    expect(calls.some(([m]) => m === 'POST')).toBe(false);
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'لغو اعتماد' }));
    await waitFor(() =>
      expect(calls.some(([m, p]) => m === 'POST' && p.endsWith('/trusted-devices/d1/revoke'))).toBe(true),
    );
    await waitFor(() => expect(toast).toHaveBeenCalledWith('اعتماد دستگاه لغو شد'));
  });

  it('offers no revoke button for a device that is already revoked', async () => {
    setup({ devices: [device({ status: 'revoked', revoked_at: '2026-10-27T11:00:00Z' })] });
    expect(await screen.findByText('لغو شده')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /لغو اعتماد/ })).toBeNull();
  });

  it('shows automatic merges with both accounts and the rule', async () => {
    setup({
      merges: [
        {
          id: 'm1',
          created_at: '2026-10-27T09:00:00Z',
          rule: 'shell_into_other',
          providers: ['google'],
          keeper: { id: 'k1111111', display_name: 'Keep', email: 'k@example.com' },
          shell: { id: 's2222222', display_name: 'Empty', email: null },
        },
      ],
    });
    await userEvent.click(await screen.findByRole('radio', { name: 'ادغام‌های خودکار' }));
    expect(await screen.findByText('Empty')).toBeInTheDocument();
    expect(screen.getByText('Keep')).toBeInTheDocument();
    expect(screen.getByText(/حساب خالی در حساب دارای سابقه ادغام شد/)).toBeInTheDocument();
  });
});
