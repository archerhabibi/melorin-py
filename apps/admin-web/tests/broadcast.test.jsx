import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import BroadcastView from '../src/BroadcastView.jsx';
import { DialogHost } from '../src/ui.jsx';

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });

function setup({ post } = {}) {
  const calls = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, o = {}) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '');
    calls.push([o.method || 'GET', path, o.body]);
    if (path.endsWith('/broadcasts/audiences'))
      return json({
        daily_limit: 10,
        audiences: [
          { id: 'all_own', label: 'همهٔ نمایندگان و مشتریان من', count: 7 },
          { id: 'resellers', label: 'فقط نمایندگان من', count: 0 },
        ],
      });
    if (o.method === 'POST') return post ? post() : json({ ok: true, id: 'b1', recipients: 7 }, 201);
    return json([]);
  });
  const toast = vi.fn();
  render(
    <>
      <BroadcastView api={{ base: 'http://core.test' }} toast={toast} />
      <DialogHost />
    </>,
  );
  return { calls, toast };
}

describe('admin broadcast (پیام همگانی)', () => {
  it('offers only the groups Core returns, with their reach, and keeps send disabled until all is filled', async () => {
    setup();
    expect(await screen.findByText('فقط نمایندگان من')).toBeInTheDocument();
    const send = screen.getByRole('button', { name: /ارسال پیام/ });
    expect(send).toBeDisabled();
    await userEvent.click(screen.getByRole('radio', { name: /همهٔ نمایندگان و مشتریان من/ }));
    await userEvent.type(screen.getByLabelText(/عنوان/), 'سلام');
    await userEvent.type(screen.getByLabelText(/^متن/), 'متن پیام');
    expect(send).toBeEnabled();
  });

  it('a group nobody belongs to cannot be sent to', async () => {
    setup();
    await userEvent.click(await screen.findByRole('radio', { name: /فقط نمایندگان من/ }));
    await userEvent.type(screen.getByLabelText(/عنوان/), 'سلام');
    await userEvent.type(screen.getByLabelText(/^متن/), 'متن');
    expect(screen.getByRole('button', { name: /ارسال پیام/ })).toBeDisabled();
  });

  it('asks for confirmation, then posts audience, title and body', async () => {
    const { calls, toast } = setup();
    await userEvent.click(await screen.findByRole('radio', { name: /همهٔ نمایندگان و مشتریان من/ }));
    await userEvent.type(screen.getByLabelText(/عنوان/), 'تعطیلی');
    await userEvent.type(screen.getByLabelText(/^متن/), 'فردا پشتیبانی نیست');
    await userEvent.click(screen.getByRole('button', { name: /ارسال پیام/ }));
    expect(calls.some(([m]) => m === 'POST')).toBe(false); // nothing is sent before the confirmation
    await userEvent.click(await screen.findByRole('button', { name: 'ارسال' }));
    await waitFor(() => expect(toast).toHaveBeenCalled());
    const post = calls.find(([m]) => m === 'POST');
    expect(post[1]).toBe('/api/v1/admin/broadcasts');
    expect(JSON.parse(post[2])).toEqual({ audience: 'all_own', title: 'تعطیلی', body: 'فردا پشتیبانی نیست' });
  });

  it("shows Core's refusal (e.g. the daily limit) instead of pretending it was sent", async () => {
    const { toast } = setup({ post: () => json({ error: { message: 'سقف ارسال پیام همگانی پر شده است.' } }, 429) });
    await userEvent.click(await screen.findByRole('radio', { name: /همهٔ نمایندگان و مشتریان من/ }));
    await userEvent.type(screen.getByLabelText(/عنوان/), 'الف');
    await userEvent.type(screen.getByLabelText(/^متن/), 'ب');
    await userEvent.click(screen.getByRole('button', { name: /ارسال پیام/ }));
    await userEvent.click(await screen.findByRole('button', { name: 'ارسال' }));
    expect(await screen.findByText('سقف ارسال پیام همگانی پر شده است.')).toBeInTheDocument();
    expect(toast).not.toHaveBeenCalled();
  });
});
