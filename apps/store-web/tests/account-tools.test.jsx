import { describe, expect, it } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AccountTools from '../src/AccountTools.tsx';

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
const T = (tool, available = true, reason = null) => ({ tool, label: tool, write: false, available, reason });
const customerMatrix = [T('usage'), T('devices'), T('devices_manage'), T('rotate')];
const ownerMatrix = [...customerMatrix, T('presence'), T('suspend')];

function mk(matrix) {
  const calls = [];
  const coreFetch = async (path, o = {}) => {
    calls.push([o.method || 'GET', path]);
    if (o.method && o.method !== 'GET') return json({ id: 'a1', username: 'x', status: 'active' });
    if (path.endsWith('/tools')) return json(matrix);
    if (path.includes('/usage'))
      return json({ period: 'day', days: 30, points: [], by_node: [], total_bytes: 3 * 2 ** 30 });
    if (path.includes('/devices'))
      return json({ count: 1, items: [{ hwid: 'h1', label: 'Pixel', platform: 'android' }] });
    if (path.includes('/presence')) return json({ online_at: null, online_now: false, never_connected: true });
    return json({});
  };
  return { calls, coreFetch };
}

const base = '/api/v1/stores/s1/vpn-accounts';

describe('AccountTools (PG-10, store site)', () => {
  it('customer: sees usage and devices but never presence or suspend, and loads lazily', async () => {
    const { calls, coreFetch } = mk(customerMatrix);
    render(<AccountTools a={{ id: 'a1', status: 'active' }} base={base} coreFetch={coreFetch} />);
    expect(calls).toHaveLength(0);
    await userEvent.click(screen.getByRole('button', { name: /ابزارهای اکانت/ }));
    expect(await screen.findByText(/Pixel/)).toBeInTheDocument();
    expect(screen.queryByText(/آخرین اتصال/)).toBeNull();
    expect(screen.queryByRole('button', { name: /تعلیق/ })).toBeNull();
    expect(calls.some(([, p]) => p.includes('/presence'))).toBe(false);
  });

  it('rotating the link takes two taps and then posts once', async () => {
    const { calls, coreFetch } = mk(customerMatrix);
    render(<AccountTools a={{ id: 'a1', status: 'active' }} base={base} coreFetch={coreFetch} notify={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: /ابزارهای اکانت/ }));
    await userEvent.click(await screen.findByRole('button', { name: /لینک اشتراک جدید/ }));
    expect(calls.some(([m]) => m === 'POST')).toBe(false);
    await userEvent.click(screen.getByRole('button', { name: /مطمئنید/ }));
    await waitFor(() =>
      expect(calls.filter(([m, p]) => m === 'POST' && p.endsWith('/tools/rotate-subscription'))).toHaveLength(1),
    );
  });

  it('owner: sees last seen and can suspend', async () => {
    const { calls, coreFetch } = mk(ownerMatrix);
    render(
      <AccountTools
        a={{ id: 'a1', status: 'active' }}
        base="/api/v1/stores/s1/reseller/accounts"
        owner
        coreFetch={coreFetch}
        notify={() => {}}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: /ابزارهای اکانت/ }));
    expect(await screen.findByText(/هنوز اتصالی ثبت نشده/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /تعلیق اکانت/ }));
    await userEvent.click(screen.getByRole('button', { name: /مطمئنید/ }));
    await waitFor(() => expect(calls.some(([m, p]) => m === 'POST' && p.endsWith('/tools/suspend'))).toBe(true));
  });

  it('a suspended account offers resume instead of suspend', async () => {
    const { coreFetch } = mk(ownerMatrix);
    render(<AccountTools a={{ id: 'a1', status: 'suspended' }} base={base} owner coreFetch={coreFetch} />);
    await userEvent.click(screen.getByRole('button', { name: /ابزارهای اکانت/ }));
    expect(await screen.findByRole('button', { name: /فعال‌سازی مجدد/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /تعلیق اکانت/ })).toBeNull();
  });
});
