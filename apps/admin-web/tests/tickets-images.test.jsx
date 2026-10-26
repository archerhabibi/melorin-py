import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import TicketsView from '../src/TicketsView.jsx';
import { PasswordInput } from '../src/ui.jsx';

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const png = () => new File([new Uint8Array([137, 80, 78, 71])], 'reply.png', { type: 'image/png' });
const NOW = '2026-10-26T05:00:00Z';
const row = {
  id: 't1',
  number: 'T-1',
  subject: 'مشکل اتصال',
  status: 'open',
  priority: 'normal',
  department: null,
  created_at: NOW,
  updated_at: NOW,
  customer: { id: 'u1', name: 'مشتری', email: 'c@example.com' },
  store_name: 'فروشگاه',
  message_count: 1,
  last_message: '📎 تصویر',
  last_from_staff: false,
};
const detail = {
  ...row,
  messages: [
    {
      id: 'm1',
      is_staff: false,
      is_internal: false,
      body: '',
      attachment_id: 'img-1',
      created_at: NOW,
      author_name: 'مشتری',
    },
  ],
};

function setup({ uploadStatus = 201 } = {}) {
  const calls = [];
  const call = vi.fn(async (path, o = {}) => {
    calls.push([o.method || 'GET', path, o.body]);
    if (path === '/api/v1/admin/tickets') return json([row]);
    if (path === '/api/v1/admin/tickets/t1') return json(detail);
    if (path === '/api/v1/admin/tickets/t1/messages/m1/attachment')
      return { ok: true, blob: async () => new Blob(['x'], { type: 'image/png' }) }; // jsdom's Blob does not mix with Node's Response
    if (path === '/api/v1/admin/tickets/attachments')
      return uploadStatus === 201
        ? json({ id: 'img-9', content_type: 'image/png', size: 4 }, 201)
        : json({ error: { message: 'حجم تصویر زیاد است.' } }, uploadStatus);
    if (path === '/api/v1/admin/tickets/t1/messages') return json({ id: 'm2' });
    return json({});
  });
  const toast = vi.fn();
  render(<TicketsView call={call} toast={toast} />);
  return { calls, call, toast };
}

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => 'blob:ticket-image');
  URL.revokeObjectURL = vi.fn();
  Element.prototype.scrollIntoView = vi.fn(); // jsdom has no layout, so no scrolling
});

async function openTicket() {
  await userEvent.click((await screen.findAllByText('مشکل اتصال'))[0]);
  return screen.findByRole('log', { name: 'گفتگو' });
}

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

describe('ticket pictures in the admin desk', () => {
  it("shows the customer's picture (a picture-only message has no empty text bubble)", async () => {
    const { calls } = setup();
    const log = await openTicket();
    expect(await screen.findByAltText('تصویر پیوست')).toHaveAttribute('src', 'blob:ticket-image');
    expect(log.querySelector('p')).toBeNull();
    expect(calls.some(([, p]) => p === '/api/v1/admin/tickets/t1/messages/m1/attachment')).toBe(true);
  });

  it('answers with a picture only: uploads first, then sends the attachment id', async () => {
    const { calls } = setup();
    await openTicket();
    const send = screen.getByRole('button', { name: 'ارسال پاسخ' });
    expect(send).toBeDisabled(); // neither text nor picture yet
    await userEvent.upload(screen.getByTestId('ticket-image-input'), png());
    expect(screen.getByText('reply.png')).toBeInTheDocument();
    expect(send).toBeEnabled();
    await userEvent.click(send);
    await waitFor(() =>
      expect(calls.some(([m, p]) => m === 'POST' && p === '/api/v1/admin/tickets/t1/messages')).toBe(true),
    );
    const upload = calls.find(([, p]) => p === '/api/v1/admin/tickets/attachments');
    expect(upload[0]).toBe('POST');
    expect(upload[2]).toBeInstanceOf(FormData);
    const reply = calls.find(([m, p]) => m === 'POST' && p === '/api/v1/admin/tickets/t1/messages');
    expect(JSON.parse(reply[2])).toMatchObject({ body: '', internal: false, attachment_id: 'img-9' });
    expect(calls.indexOf(upload)).toBeLessThan(calls.indexOf(reply));
  });

  it('refuses a non-image before anything is uploaded', async () => {
    const { calls, toast } = setup();
    await openTicket();
    const pdf = new File(['%PDF'], 'doc.pdf', { type: 'application/pdf' });
    await userEvent.upload(screen.getByTestId('ticket-image-input'), pdf, { applyAccept: false });
    expect(toast).toHaveBeenCalledWith('فقط تصویر (JPG، PNG یا WebP) مجاز است.');
    expect(screen.queryByText('doc.pdf')).not.toBeInTheDocument();
    expect(calls.some(([, p]) => p === '/api/v1/admin/tickets/attachments')).toBe(false);
  });

  it('reports a failed upload and sends no message', async () => {
    const { calls, toast } = setup({ uploadStatus: 413 });
    await openTicket();
    await userEvent.upload(screen.getByTestId('ticket-image-input'), png());
    await userEvent.click(screen.getByRole('button', { name: 'ارسال پاسخ' }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith('حجم تصویر زیاد است.'));
    expect(calls.some(([m, p]) => m === 'POST' && p === '/api/v1/admin/tickets/t1/messages')).toBe(false);
    expect(screen.getByText('reply.png')).toBeInTheDocument(); // still there for a retry
  });
});
