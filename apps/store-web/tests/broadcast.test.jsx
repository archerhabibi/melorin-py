import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ResellerBroadcast from '../src/ResellerBroadcast.jsx';

const res = (body, status = 200) => new Response(JSON.stringify(body), { status });

function setup({ reach = 12, post } = {}) {
  const calls = [];
  const coreFetch = vi.fn(async (path, o = {}) => {
    calls.push([o.method || 'GET', path, o.body]);
    if (o.method === 'POST') return post ? post() : res({ ok: true, id: 'b1', recipients: reach }, 201);
    return res({
      daily_limit: 10,
      audiences: [{ id: 'customers', label: 'مشتریان فروشگاه من', count: reach }],
      items: [],
    });
  });
  const notify = vi.fn();
  render(<ResellerBroadcast coreFetch={coreFetch} base="/api/v1/stores/s1/reseller" notify={notify} />);
  return { calls, notify };
}

describe('reseller broadcast (پیام همگانی)', () => {
  it('has no audience choice: it only ever reaches the reseller’s own store customers', async () => {
    setup();
    expect(await screen.findByText(/۱۲ مشتری فعال/)).toBeInTheDocument();
    expect(screen.queryByRole('radio')).toBeNull();
  });

  it('posts only title and body (Core fixes the audience) after the browser confirmation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const { calls, notify } = setup();
    await userEvent.type(await screen.findByLabelText(/عنوان/), 'تخفیف');
    await userEvent.type(screen.getByLabelText(/متن پیام/), 'تا فردا ۲۰٪ تخفیف');
    await userEvent.click(screen.getByRole('button', { name: /ارسال پیام/ }));
    await waitFor(() => expect(notify).toHaveBeenCalled());
    const post = calls.find(([m]) => m === 'POST');
    expect(post[1]).toBe('/api/v1/stores/s1/reseller/broadcasts');
    expect(JSON.parse(post[2])).toEqual({ title: 'تخفیف', body: 'تا فردا ۲۰٪ تخفیف' });
  });

  it('does not send when the reseller declines the confirmation, or when the store has no customers', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    const { calls } = setup();
    await userEvent.type(await screen.findByLabelText(/عنوان/), 'الف');
    await userEvent.type(screen.getByLabelText(/متن پیام/), 'ب');
    await userEvent.click(screen.getByRole('button', { name: /ارسال پیام/ }));
    expect(calls.some(([m]) => m === 'POST')).toBe(false);
  });

  it('keeps the button disabled when there are no customers to reach', async () => {
    setup({ reach: 0 });
    await userEvent.type(await screen.findByLabelText(/عنوان/), 'الف');
    await userEvent.type(screen.getByLabelText(/متن پیام/), 'ب');
    expect(screen.getByRole('button', { name: /ارسال پیام/ })).toBeDisabled();
  });
});
