import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PanelsView from '../src/PanelsView.jsx';
import { DialogHost } from '../src/ui.jsx';

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const SESSION = '1' + 'B'.repeat(150);
const PANEL = {
  id: '11111111-1111-4111-8111-111111111111',
  name: 'ربات والد',
  kind: 'upstream_bot',
  base_url: 'https://t.me/parent_bot',
  is_enabled: true,
  health_status: 'healthy',
  last_health_at: new Date().toISOString(),
  last_health_error: null,
  has_credentials: true,
  config: { max_price: 100000, service_button: 'سرویس ویژه', renew: { enabled: false } },
  created_at: '2026-10-01T00:00:00Z',
  updated_at: '2026-10-01T00:00:00Z',
};

function mockApi(panels) {
  const calls = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, o = {}) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '');
    const method = o.method || 'GET';
    calls.push([method, path, o.body]);
    if (method === 'GET' && path === '/api/v1/admin/panels') return json(panels);
    if (method === 'GET') return json([]);
    if (method === 'POST' && path === '/api/v1/admin/panels') return json({ id: 'new-id' }, 201);
    if (method === 'POST' && path === '/api/v1/admin/servers') return json({ id: 'srv' }, 201);
    return json({ ok: true });
  });
  return calls;
}

const setup = () =>
  render(
    <>
      <PanelsView api={{ base: 'http://core.test' }} toast={vi.fn()} />
      <DialogHost />
    </>,
  );

describe('PanelsView · upstream_bot', () => {
  it('shows the safety cap and renewal state on the panel card', async () => {
    mockApi([PANEL]);
    setup();
    expect(await screen.findByText('@parent_bot')).toBeTruthy();
    expect(screen.getByText(/سقف خرید/)).toBeTruthy();
    expect(screen.getByText('تمدید غیرفعال')).toBeTruthy();
  });

  it('edits settings without asking for or re-sending the stored Telethon session', async () => {
    const calls = mockApi([PANEL]);
    setup();
    await userEvent.click(await screen.findByRole('button', { name: /ویرایش/ }));
    // stored settings are loaded into the form; credentials stay hidden behind "change"
    expect(await screen.findByDisplayValue('parent_bot')).toBeTruthy();
    expect(screen.getByDisplayValue('100,000')).toBeTruthy();
    expect(screen.getByDisplayValue('سرویس ویژه')).toBeTruthy();
    expect(screen.queryByText('api_hash')).toBeNull();

    const cap = screen.getByLabelText('سقف مبلغ هر خرید یا تمدید');
    await userEvent.clear(cap);
    await userEvent.type(cap, '150000');
    await userEvent.click(screen.getByRole('button', { name: 'فقط ذخیره' }));

    await waitFor(() => expect(calls.some((c) => c[0] === 'PATCH')).toBe(true));
    const [, path, body] = calls.find((c) => c[0] === 'PATCH');
    expect(path).toBe(`/api/v1/admin/panels/${PANEL.id}`);
    expect(JSON.parse(body)).toEqual({
      name: 'ربات والد',
      kind: 'upstream_bot',
      base_url: 'https://t.me/parent_bot',
      credentials: {},
      config: { max_price: 150000, service_button: 'سرویس ویژه', renew: { enabled: false } },
    });
  });

  it('creates a panel from a pasted t.me link with credentials, cap and the first server', async () => {
    const calls = mockApi([]);
    setup();
    await userEvent.click((await screen.findAllByRole('button', { name: /افزودن پنل|پنل جدید/ }))[0]);
    await userEvent.click(await screen.findByRole('radio', { name: /ربات واسط/ }));

    // nothing is sent while the form is invalid
    await userEvent.click(screen.getByRole('button', { name: 'فقط ثبت' }));
    expect(await screen.findByText(/نام پنل را وارد کنید/)).toBeTruthy();
    expect(calls.some((c) => c[0] === 'POST')).toBe(false);

    await userEvent.type(screen.getByPlaceholderText(/ربات والد - سرویس اقتصادی/), 'والد اقتصادی');
    await userEvent.type(screen.getByLabelText('نام کاربری ربات والد'), 'https://t.me/Parent_Bot/');
    await userEvent.type(screen.getByPlaceholderText('1234567'), '123456');
    await userEvent.type(screen.getByPlaceholderText('0123456789abcdef0123456789abcdef'), 'a'.repeat(32));
    await userEvent.type(screen.getByPlaceholderText('1BVtsOKEBu7...'), SESSION);
    await userEvent.click(screen.getByRole('button', { name: /100,000|۱۰۰٬۰۰۰/ }));
    await userEvent.click(screen.getByRole('button', { name: 'فقط ثبت' }));

    await waitFor(() => expect(calls.some((c) => c[0] === 'POST' && c[1] === '/api/v1/admin/panels')).toBe(true));
    const body = JSON.parse(calls.find((c) => c[0] === 'POST' && c[1] === '/api/v1/admin/panels')[2]);
    expect(body).toEqual({
      name: 'والد اقتصادی',
      kind: 'upstream_bot',
      base_url: 'https://t.me/Parent_Bot',
      credentials: { api_id: 123456, api_hash: 'a'.repeat(32), session: SESSION },
      config: { max_price: 100000, renew: { enabled: true } },
    });
    expect(body.config).not.toHaveProperty('verify_tls');
    await waitFor(() => expect(calls.some((c) => c[1] === '/api/v1/admin/servers')).toBe(true));
  });

  it('previews the flow with the configured button texts', async () => {
    mockApi([]);
    setup();
    await userEvent.click((await screen.findAllByRole('button', { name: /افزودن پنل|پنل جدید/ }))[0]);
    await userEvent.click(await screen.findByRole('radio', { name: /ربات واسط/ }));
    const flow = screen.getByRole('list', { name: /مسیر خرید/ });
    expect(within(flow).getByText('خرید اکانت')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: /متن دکمه‌های ربات والد/ }));
    const menu = screen.getByPlaceholderText('خرید اکانت');
    await userEvent.type(menu, 'خرید جدید');
    expect(within(screen.getByRole('list', { name: /مسیر خرید/ })).getByText('خرید جدید')).toBeTruthy();
  });
});
