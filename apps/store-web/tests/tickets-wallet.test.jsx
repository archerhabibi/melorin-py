import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Dashboard, { Tickets, Wallet } from '../src/Dashboard.tsx';
import { PasswordInput } from '../src/ui.tsx';
import { readAttempt, resetAttemptStorage } from './attemptStorage.js';

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const png = () => new File([new Uint8Array([137, 80, 78, 71])], 'screen.png', { type: 'image/png' });

beforeEach(() => {
  resetAttemptStorage();
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
    render(<Wallet accountId="u1" {...base} wallet={{ balance: 1000, currency: 'IRT', telegram_id: '123456789' }} />);
    expect(screen.getByText('آیدی عددی تلگرام')).toBeInTheDocument();
    expect(screen.getByText('123456789')).toBeInTheDocument();
  });

  it('says so when no Telegram account is linked', async () => {
    render(<Wallet accountId="u1" {...base} wallet={{ balance: 0, currency: 'IRT', telegram_id: null }} />);
    expect(screen.getByText('متصل نیست')).toBeInTheDocument();
  });

  it('reuses the persisted idempotency key after an ambiguous response and a page reload', async () => {
    const keys = [];
    let posts = 0;
    const coreFetch = vi.fn(async (path, opts = {}) => {
      if (path.endsWith('/wallet/transactions')) return json([]);
      if (path.endsWith('/wallet/topups') && opts.method === 'POST') {
        posts += 1;
        keys.push(opts.headers['Idempotency-Key']);
        if (posts === 1)
          return json({ error: { code: 'PAYMENT_INTENT_OUTCOME_UNKNOWN', message: 'نتیجه نامعلوم' } }, 503);
        return json({
          id: 'p1',
          amount: 1000,
          currency: 'IRT',
          status: 'pending',
          instructions: { card_number: '1234' },
        });
      }
      return json([]);
    });
    const notify = vi.fn();
    const first = render(<Wallet accountId="u1" coreFetch={coreFetch} storeId="s1" notify={notify} />);
    await userEvent.type(screen.getByPlaceholderText('مبلغ'), '1000');
    await userEvent.click(screen.getByRole('button', { name: 'ایجاد درخواست' }));
    await waitFor(() => expect(notify).toHaveBeenCalledWith('نتیجه نامعلوم'));
    expect(await readAttempt('melorin:wallet-topup:s1:u1')).toContain(keys[0]);

    first.unmount();
    render(<Wallet accountId="u1" coreFetch={coreFetch} storeId="s1" notify={notify} />);
    await userEvent.type(screen.getByPlaceholderText('مبلغ'), '1000');
    await userEvent.click(screen.getByRole('button', { name: 'ایجاد درخواست' }));
    await waitFor(() => expect(posts).toBe(2));

    expect(keys[1]).toBe(keys[0]);
    expect(await readAttempt('melorin:wallet-topup:s1:u1')).toContain(keys[0]);
    expect(screen.getByText('1234')).toBeInTheDocument();
  });

  it('does not create a new payment key when an unresolved attempt exists for another amount', async () => {
    let posts = 0;
    const coreFetch = vi.fn(async (path, opts = {}) => {
      if (path.endsWith('/wallet/transactions')) return json([]);
      if (path.endsWith('/wallet/topups') && opts.method === 'POST') {
        posts += 1;
        return json({ error: { code: 'PAYMENT_INTENT_OUTCOME_UNKNOWN', message: 'نتیجه نامعلوم' } }, 503);
      }
      return json([]);
    });
    const notify = vi.fn();
    render(<Wallet accountId="u1" coreFetch={coreFetch} storeId="s1" notify={notify} />);
    const amount = screen.getByPlaceholderText('مبلغ');
    await userEvent.type(amount, '1000');
    await userEvent.click(screen.getByRole('button', { name: 'ایجاد درخواست' }));
    await waitFor(() => expect(posts).toBe(1));

    await userEvent.clear(amount);
    await userEvent.type(amount, '2000');
    await userEvent.click(screen.getByRole('button', { name: 'ایجاد درخواست' }));

    expect(posts).toBe(1);
    expect(notify).toHaveBeenLastCalledWith(expect.stringContaining('درخواست شارژ قبلی'));
  });

  it('isolates unresolved topups when different customers use the same browser', async () => {
    const keys = [];
    const coreFetch = vi.fn(async (path, opts = {}) => {
      if (path.endsWith('/wallet/transactions')) return json([]);
      if (path.endsWith('/wallet/topups') && opts.method === 'POST') {
        keys.push(opts.headers['Idempotency-Key']);
        if (keys.length < 3)
          return json({ error: { code: 'PAYMENT_INTENT_OUTCOME_UNKNOWN', message: 'نامعلوم' } }, 503);
        return json({ id: 'p1', amount: 1000, currency: 'IRT', status: 'pending', instructions: {} });
      }
      return json([]);
    });
    const first = render(<Wallet accountId="user-a" coreFetch={coreFetch} storeId="s1" notify={() => {}} />);
    await userEvent.type(screen.getByPlaceholderText('مبلغ'), '1000');
    await userEvent.click(screen.getByRole('button', { name: 'ایجاد درخواست' }));
    await waitFor(() => expect(keys).toHaveLength(1));
    first.unmount();

    const second = render(<Wallet accountId="user-b" coreFetch={coreFetch} storeId="s1" notify={() => {}} />);
    await userEvent.type(screen.getByPlaceholderText('مبلغ'), '2000');
    await userEvent.click(screen.getByRole('button', { name: 'ایجاد درخواست' }));
    await waitFor(() => expect(keys).toHaveLength(2));
    expect(keys[1]).not.toBe(keys[0]);
    second.unmount();

    render(<Wallet accountId="user-a" coreFetch={coreFetch} storeId="s1" notify={() => {}} />);
    await userEvent.type(screen.getByPlaceholderText('مبلغ'), '1000');
    await userEvent.click(screen.getByRole('button', { name: 'ایجاد درخواست' }));
    await waitFor(() => expect(keys).toHaveLength(3));
    expect(keys[2]).toBe(keys[0]);
  });

  it('does not allow a topup before the account identity is available', async () => {
    const coreFetch = vi.fn(async () => json([]));
    render(<Wallet coreFetch={coreFetch} storeId="s1" notify={() => {}} />);
    await userEvent.type(screen.getByPlaceholderText('مبلغ'), '1000');
    expect(screen.getByRole('button', { name: 'ایجاد درخواست' })).toBeDisabled();
  });

  it('uses the signed-in account when the wallet is opened from the dashboard', async () => {
    const keys = [];
    const coreFetch = vi.fn(async (path, opts = {}) => {
      if (path.includes('/notifications')) return json({ unread: 0, items: [] });
      if (path.endsWith('/wallet/transactions')) return json([]);
      if (path.endsWith('/wallet/topups') && opts.method === 'POST') {
        keys.push(opts.headers['Idempotency-Key']);
        return json({ error: { code: 'PAYMENT_INTENT_OUTCOME_UNKNOWN', message: 'نامعلوم' } }, 503);
      }
      return json([]);
    });
    render(
      <Dashboard
        account={{ id: 'user-c' }}
        coreFetch={coreFetch}
        storeId="s1"
        wallet={{ balance: 0, currency: 'IRT' }}
        orders={[]}
        reload={() => {}}
        notify={() => {}}
        onLogout={() => {}}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'کیف پول' }));
    await userEvent.type(screen.getByPlaceholderText('مبلغ'), '1000');
    await userEvent.click(screen.getByRole('button', { name: 'ایجاد درخواست' }));
    await waitFor(() => expect(keys).toHaveLength(1));
    expect(await readAttempt('melorin:wallet-topup:s1:user-c')).toContain(keys[0]);
  });

  it('allows a different amount once the previous payment was received (no dead end after reload)', async () => {
    const keys = [];
    const coreFetch = vi.fn(async (path, opts = {}) => {
      if (path.endsWith('/wallet/transactions')) return json([]);
      if (path.endsWith('/wallet/topups') && opts.method === 'POST') {
        keys.push(opts.headers['Idempotency-Key']);
        return json({
          id: `p${keys.length}`,
          amount: 1,
          currency: 'IRT',
          status: 'pending',
          instructions: { card_number: '1234' },
        });
      }
      return json([]);
    });
    const notify = vi.fn();
    const first = render(<Wallet accountId="u1" coreFetch={coreFetch} storeId="s1" notify={notify} />);
    await userEvent.type(screen.getByPlaceholderText('مبلغ'), '1000');
    await userEvent.click(screen.getByRole('button', { name: 'ایجاد درخواست' }));
    await waitFor(() => expect(keys).toHaveLength(1));
    first.unmount();

    render(<Wallet accountId="u1" coreFetch={coreFetch} storeId="s1" notify={notify} />);
    await userEvent.type(screen.getByPlaceholderText('مبلغ'), '2000');
    await userEvent.click(screen.getByRole('button', { name: 'ایجاد درخواست' }));
    await waitFor(() => expect(keys).toHaveLength(2));
    expect(keys[1]).not.toBe(keys[0]);
    expect(notify).not.toHaveBeenCalled();
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
