import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import EventCenterView from '../src/EventCenterView.jsx';

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
const topics = [
  { key: 'payments', label: 'پرداخت‌ها', thread_id: 7 },
  { key: 'orders', label: 'سفارش‌ها', thread_id: null },
];

describe('EventCenterView', () => {
  it('shows saved settings and saves normalised Topic ids', async () => {
    const calls = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, o = {}) => {
      const path = String(url).replace(/^https?:\/\/[^/]+/, '');
      calls.push([o.method || 'GET', path, o.body]);
      const view = {
        configured: true,
        bot_ready: true,
        chat_id: '-1001234567890',
        is_enabled: true,
        note: null,
        topics,
      };
      return json(view);
    });
    const toast = vi.fn();
    render(<EventCenterView api={{ base: 'http://core.test' }} toast={toast} />);
    const chat = await screen.findByDisplayValue('-1001234567890');
    expect(chat).toBeTruthy();
    await userEvent.type(screen.getAllByPlaceholderText('General')[1], '۱۲');
    await userEvent.click(screen.getByRole('button', { name: /ذخیره/ }));
    await waitFor(() => expect(toast).toHaveBeenCalled());
    const put = calls.find((c) => c[0] === 'PUT');
    expect(put[1]).toBe('/api/v1/admin/event-center');
    expect(JSON.parse(put[2])).toMatchObject({ chat_id: '-1001234567890', topics: { payments: '7', orders: '12' } });
  });

  it('checks the group and creates missing Topics through the provision endpoint', async () => {
    const calls = [];
    let created = false;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, o = {}) => {
      const path = String(url).replace(/^https?:\/\/[^/]+/, '');
      calls.push([o.method || 'GET', path]);
      if (path.endsWith('/check'))
        return json({
          ok: false,
          title: 'Ops',
          bot_username: 'shop_bot',
          problems: ['قابلیت Topics گروه خاموش است'],
          missing_topics: ['orders'],
        });
      if (path.endsWith('/provision')) {
        created = true;
        return json({ created: 1, results: [{ topic: 'orders', label: 'سفارش‌ها', status: 'created', thread_id: 9 }] });
      }
      return json({
        configured: true,
        bot_ready: true,
        chat_id: '-1001234567890',
        is_enabled: true,
        note: null,
        topics: [topics[0], { ...topics[1], thread_id: created ? 9 : null }],
      });
    });
    const toast = vi.fn();
    render(<EventCenterView api={{ base: 'http://core.test' }} toast={toast} />);
    await screen.findByDisplayValue('-1001234567890');
    await userEvent.click(screen.getByRole('button', { name: /بررسی گروه/ }));
    expect(await screen.findByText(/قابلیت Topics گروه خاموش است/)).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: /ساخت خودکار/ }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith('1 Topic ساخته شد'));
    expect(await screen.findByDisplayValue('9')).toBeTruthy();
    expect(calls.filter((c) => c[0] === 'POST').map((c) => c[1])).toEqual([
      '/api/v1/admin/event-center/check',
      '/api/v1/admin/event-center/provision',
    ]);
  });
});
