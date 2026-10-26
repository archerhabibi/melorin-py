import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Tickets, Wallet } from '../src/Dashboard.jsx';
import { PasswordInput } from '../src/ui.jsx';

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const png = () => new File([new Uint8Array([137, 80, 78, 71])], 'screen.png', { type: 'image/png' });

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => 'blob:ticket-image');
  URL.revokeObjectURL = vi.fn();
  Element.prototype.scrollIntoView = vi.fn(); // jsdom has no layout, so no scrolling
});

describe('PasswordInput (eye toggle)', () => {
  it('hides the secret by default and shows / hides it with the eye button', async () => {
    render(<PasswordInput aria-label="رمز" defaultValue="s3cret" />);
    const input = screen.getByLabelText('رمز');
    expect(input).toHaveAttribute('type', 'password');
    await userEvent.click(screen.getByRole('button', { name: 'نمایش رمز' }));
    expect(input).toHaveAttribute('type', 'text');
    await userEvent.click(screen.getByRole('button', { name: 'پنهان‌کردن رمز' }));
    expect(input).toHaveAttribute('type', 'password');
  });
});

describe('Wallet shows the Telegram ID', () => {
  const coreFetch = vi.fn(async () => json([]));
  const base = { coreFetch, storeId: 's1', reload: () => {}, notify: () => {} };

  it('shows the numeric Telegram ID of the owner', async () => {
    render(<Wallet {...base} wallet={{ balance: 1000, currency: 'IRT', telegram_id: '123456789' }} />);
    expect(screen.getByText('آیدی عددی تلگرام')).toBeInTheDocument();
    expect(screen.getByText('123456789')).toBeInTheDocument();
  });

  it('says so when no Telegram account is linked', async () => {
    render(<Wallet {...base} wallet={{ balance: 0, currency: 'IRT', telegram_id: null }} />);
    expect(screen.getByText('متصل نیست')).toBeInTheDocument();
  });
});

describe('Tickets take pictures', () => {
  it('creates a ticket with only a picture: uploads first, then sends the attachment id', async () => {
    const calls = [];
    const coreFetch = vi.fn(async (path, opts = {}) => {
      calls.push([path, opts]);
      if (path === '/api/v1/stores/s1/tickets' && !opts.method) return json([]);
      if (path === '/api/v1/stores/s1/tickets/attachments')
        return json({ id: 'img-1', content_type: 'image/png', size: 4 }, 201);
      if (path === '/api/v1/stores/s1/tickets' && opts.method === 'POST')
        return json(
          {
            id: 't1',
            number: 'T-1',
            subject: 'مشکل',
            status: 'open',
            priority: 'normal',
            created_at: '2026-10-26T05:00:00Z',
          },
          201,
        );
      if (path === '/api/v1/tickets/t1/messages')
        return json([
          { id: 'm1', is_staff: false, body: '', attachment_id: 'img-1', created_at: '2026-10-26T05:00:00Z' },
        ]);
      if (path.endsWith('/attachment')) return { ok: true, blob: async () => new Blob(['x'], { type: 'image/png' }) }; // jsdom's Blob does not mix with Node's Response
      return json([]);
    });
    const notify = vi.fn();
    render(<Tickets coreFetch={coreFetch} storeId="s1" notify={notify} />);

    await userEvent.click(await screen.findByRole('button', { name: /تیکت جدید/ }));
    await userEvent.type(screen.getByPlaceholderText(/موضوع/), 'مشکل');
    const submit = screen.getByRole('button', { name: 'ثبت تیکت' });
    expect(submit).toBeDisabled(); // neither text nor picture yet

    await userEvent.upload(screen.getByTestId('ticket-image-input'), png());
    expect(screen.getByText('screen.png')).toBeInTheDocument();
    expect(submit).toBeEnabled();
    await userEvent.click(submit);

    await waitFor(() => expect(notify).toHaveBeenCalledWith('تیکت #T-1 ثبت شد'));
    const upload = calls.find(([p]) => p === '/api/v1/stores/s1/tickets/attachments');
    expect(upload[1].method).toBe('POST');
    expect(upload[1].body).toBeInstanceOf(FormData);
    expect(upload[1].headers).toBeUndefined(); // the browser sets the multipart boundary itself
    const create = calls.find(([p, o]) => p === '/api/v1/stores/s1/tickets' && o.method === 'POST');
    expect(JSON.parse(create[1].body)).toMatchObject({ subject: 'مشکل', body: '', attachment_id: 'img-1' });
    // the thread opens and the picture is fetched with the login token, then shown
    expect(await screen.findByAltText('تصویر پیوست')).toHaveAttribute('src', 'blob:ticket-image');
  });

  it('rejects a non-image before anything is uploaded', async () => {
    const coreFetch = vi.fn(async () => json([]));
    const notify = vi.fn();
    render(<Tickets coreFetch={coreFetch} storeId="s1" notify={notify} />);
    await userEvent.click(await screen.findByRole('button', { name: /تیکت جدید/ }));
    const pdf = new File(['%PDF'], 'doc.pdf', { type: 'application/pdf' });
    await userEvent.upload(screen.getByTestId('ticket-image-input'), pdf, { applyAccept: false });
    expect(notify).toHaveBeenCalledWith('فقط تصویر (JPG، PNG یا WebP) مجاز است.');
    expect(screen.queryByText('doc.pdf')).not.toBeInTheDocument();
    expect(coreFetch).not.toHaveBeenCalledWith(expect.stringContaining('attachments'), expect.anything());
  });

  it('keeps the uploaded id when sending fails, so a retry never uploads the picture twice', async () => {
    let posts = 0;
    let uploads = 0;
    const coreFetch = vi.fn(async (path, opts = {}) => {
      if (path === '/api/v1/stores/s1/tickets' && !opts.method)
        return json([
          {
            id: 't1',
            number: 'T-1',
            subject: 'مشکل',
            status: 'open',
            priority: 'normal',
            updated_at: '2026-10-26T05:00:00Z',
          },
        ]);
      if (path === '/api/v1/stores/s1/tickets/attachments') {
        uploads += 1;
        return json({ id: 'img-9', content_type: 'image/png', size: 4 }, 201);
      }
      if (path === '/api/v1/tickets/t1/messages' && opts.method === 'POST') {
        posts += 1;
        return posts === 1 ? json({ error: { message: 'خطای موقت' } }, 500) : json({ id: 'm2' });
      }
      return json([]);
    });
    const notify = vi.fn();
    render(<Tickets coreFetch={coreFetch} storeId="s1" notify={notify} />);
    await userEvent.click(await screen.findByText('مشکل'));
    await userEvent.upload(await screen.findByTestId('ticket-image-input'), png());
    const send = screen.getByRole('button', { name: 'ارسال' });
    await userEvent.click(send);
    await waitFor(() => expect(notify).toHaveBeenCalledWith('خطای موقت'));
    await userEvent.click(screen.getByRole('button', { name: 'ارسال' }));
    await waitFor(() => expect(posts).toBe(2));
    expect(uploads).toBe(1);
  });
});
