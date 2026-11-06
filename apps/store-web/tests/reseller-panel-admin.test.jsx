import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ResellerPanelAdmin from '../src/ResellerPanelAdmin.jsx';

const res = (body, status = 200) => new Response(JSON.stringify(body), { status });
const BASE = '/api/v1/stores/s1/reseller';
const ADMIN = {
  panel_name: 'Panel DE',
  username: 'rs_paris',
  role: 'operator',
  status: 'active',
  profile: { profile_title: 'Paris VPN', discord_webhook: 'https://discord.com/api/webhooks/123/very-secret-token' },
  profile_synced: true,
};

function fake({ admins = [ADMIN], requests = [], post } = {}) {
  const calls = [];
  const coreFetch = vi.fn(async (path, init = {}) => {
    calls.push([path, init.method || 'GET', init.body]);
    if (path === `${BASE}/panel-admin`) return res(admins);
    if (path === `${BASE}/panel-admin/change-requests` && !init.method) return res(requests);
    return post ? post(path, init) : res({ ok: true });
  });
  return { coreFetch, calls };
}
const mount = (f, notify = vi.fn()) => {
  render(<ResellerPanelAdmin coreFetch={f.coreFetch} base={BASE} notify={notify} />);
  return notify;
};

describe('reseller › panel admin', () => {
  it('shows the store admin read-only, never a password, and hides the webhook secret', async () => {
    mount(fake());
    expect(await screen.findByText('Panel DE')).toBeInTheDocument();
    expect(screen.getByText('rs_paris')).toBeInTheDocument();
    expect(screen.getByText('Paris VPN')).toBeInTheDocument();
    expect(screen.queryByText(/very-secret-token/)).toBeNull();
    expect(screen.queryByText(/password|رمز عبور/i)).toBeNull();
  });

  it('sends only the changed fields (an emptied Telegram ID is "unchanged") with the message', async () => {
    const f = fake();
    const notify = mount(f);
    await screen.findByText('Panel DE');
    const send = screen.getByRole('button', { name: /ارسال درخواست/ });
    expect(send).toBeDisabled();
    const title = screen.getByLabelText(/عنوان پروفایل/);
    await userEvent.clear(title);
    await userEvent.type(title, 'Paris Mobile');
    await userEvent.type(screen.getByLabelText(/توضیح برای ادمین/), 'لطفاً عوض کنید');
    await userEvent.click(send);
    await waitFor(() => expect(notify).toHaveBeenCalled());
    const post = f.calls.find(([, m]) => m === 'POST');
    expect(post[0]).toBe(`${BASE}/panel-admin/change-requests`);
    expect(JSON.parse(post[2])).toEqual({ changes: { profile_title: 'Paris Mobile' }, message: 'لطفاً عوض کنید' });
  });

  it('blocks a non-numeric Telegram ID before it reaches Core', async () => {
    mount(fake());
    await screen.findByText('Panel DE');
    await userEvent.type(screen.getByLabelText(/آیدی عددی تلگرام/), 'abc');
    expect(screen.getByRole('button', { name: /ارسال درخواست/ })).toBeDisabled();
  });

  it('shows Core’s reason when the request is refused', async () => {
    const f = fake({ post: () => res({ error: { message: 'یک درخواست تغییر در انتظار بررسی دارید.' } }, 409) });
    mount(f);
    await screen.findByText('Panel DE');
    await userEvent.type(screen.getByLabelText(/لینک پشتیبانی/), 'https://t.me/paris');
    await userEvent.click(screen.getByRole('button', { name: /ارسال درخواست/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent('در انتظار بررسی');
  });

  it('with a pending request: no new form, the request can be cancelled', async () => {
    const f = fake({
      requests: [
        {
          id: 'r1',
          status: 'pending',
          changes: { profile_title: 'X' },
          message: null,
          created_at: '2026-11-06T04:00:00Z',
        },
      ],
    });
    mount(f);
    expect(await screen.findByTestId('request-pending')).toBeInTheDocument();
    expect(screen.queryByTestId('change-request-form')).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: /لغو درخواست/ }));
    await waitFor(() =>
      expect(f.calls.some(([p, m]) => p === `${BASE}/panel-admin/change-requests/r1/cancel` && m === 'POST')).toBe(
        true,
      ),
    );
  });

  it('lists the history with the admin’s note, and explains an admin that is not created yet', async () => {
    mount(
      fake({
        requests: [
          {
            id: 'r2',
            status: 'rejected',
            changes: { support_url: 'https://x.io' },
            review_note: 'آدرس معتبر نیست',
            created_at: '2026-11-05T10:00:00Z',
          },
        ],
      }),
    );
    expect(await screen.findByText(/آدرس معتبر نیست/)).toBeInTheDocument();
  });

  it('empty state when no admin exists yet, and a failure state when Core is down', async () => {
    const { unmount } = render(
      <ResellerPanelAdmin coreFetch={fake({ admins: [] }).coreFetch} base={BASE} notify={vi.fn()} />,
    );
    expect(await screen.findByText(/هنوز روی پنل ساخته نشده/)).toBeInTheDocument();
    expect(screen.queryByTestId('change-request-form')).toBeNull();
    unmount();
    render(<ResellerPanelAdmin coreFetch={vi.fn(async () => res({}, 500))} base={BASE} notify={vi.fn()} />);
    expect(await screen.findByText(/در دسترس نیست/)).toBeInTheDocument();
  });
});
