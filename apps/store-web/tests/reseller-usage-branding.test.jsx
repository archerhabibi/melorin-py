import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ResellerUsage from '../src/ResellerUsage.tsx';
import ResellerSubBranding from '../src/ResellerSubBranding.tsx';

const res = (body, status = 200) => new Response(JSON.stringify(body), { status });
const BASE = '/api/v1/stores/s1/reseller';
const REPORT = {
  live: true,
  note: null,
  taken_at: '2026-11-09T10:00:00Z',
  complete: true,
  accounts: { total: 7, active: 5, on_hold: 0, limited: 1, expired: 1, disabled: 0, other: 0 },
  usage: { total_used_bytes: 3 * 1024 ** 3 },
  near_expiry: 2,
  near_expiry_days: 3,
  near_exhaustion: 1,
  near_exhaustion_percent: 90,
  top_consumers: [
    { username: 'main_a1', used_bytes: 2 * 1024 ** 3, limit_bytes: 10 * 1024 ** 3, percent: 20, status: 'active' },
  ],
  panels: [{ name: 'Panel DE', ok: true }],
};

describe('reseller › usage report', () => {
  it('shows the live summary and nothing about IPs or links', async () => {
    const coreFetch = vi.fn(async () => res(REPORT));
    render(<ResellerUsage coreFetch={coreFetch} base={BASE} notify={vi.fn()} />);
    expect(await screen.findByTestId('usage-report')).toBeInTheDocument();
    expect(screen.getByText('main_a1', { exact: false })).toBeInTheDocument();
    expect(coreFetch).toHaveBeenCalledWith(`${BASE}/usage-report`);
    expect(screen.queryByText(/آی‌پی(?! یا)|https?:\/\//)).toBeNull();
  });

  it('shows "temporarily unavailable" and no number when the panel did not answer', async () => {
    const down = {
      live: false,
      note: 'اطلاعات زنده از پنل موقتاً در دسترس نیست.',
      taken_at: REPORT.taken_at,
      complete: false,
      panels: [{ name: 'Panel DE', ok: false }],
    };
    render(<ResellerUsage coreFetch={vi.fn(async () => res(down))} base={BASE} notify={vi.fn()} />);
    expect(await screen.findByTestId('usage-unavailable')).toHaveTextContent('موقتاً در دسترس نیست');
    expect(screen.queryByText('مصرف کل')).toBeNull();
  });

  it('shows the unavailable screen when the request fails', async () => {
    render(<ResellerUsage coreFetch={vi.fn(async () => res({}, 500))} base={BASE} notify={vi.fn()} />);
    expect(await screen.findByText(/موقتاً در دسترس نیست/)).toBeInTheDocument();
  });
});

describe('reseller › sub branding', () => {
  it('sends only the changed field and an emptied field as "" (clear)', async () => {
    const calls = [];
    const coreFetch = vi.fn(async (path, init = {}) => {
      calls.push([path, init.method || 'GET', init.body]);
      if (!init.method)
        return res({ fields: { display_name: 'Paris VPN', support_url: 'https://t.me/x' }, applied_on: [] });
      return res({ fields: {}, note: 'ذخیره شد.' });
    });
    const notify = vi.fn();
    render(<ResellerSubBranding coreFetch={coreFetch} base={BASE} notify={notify} />);
    const save = await screen.findByRole('button', { name: /ذخیره/ });
    expect(save).toBeDisabled();
    await userEvent.clear(screen.getByLabelText(/لینک پشتیبانی/));
    await userEvent.type(screen.getByLabelText(/لینک لوگو/), 'https://cdn.example.com/l.png');
    await userEvent.click(save);
    await waitFor(() => expect(notify).toHaveBeenCalled());
    const put = calls.find((c) => c[1] === 'PUT');
    expect(put[0]).toBe(`${BASE}/sub-branding`);
    expect(JSON.parse(put[2])).toEqual({ support_url: '', logo_url: 'https://cdn.example.com/l.png' });
  });
});
