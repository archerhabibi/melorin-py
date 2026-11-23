import { act, render, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Wallet } from '../src/dashboard/DashboardWallet.tsx';
import { withAttemptLock } from '../src/attemptLock.ts';

vi.mock('../src/attemptLock.ts', () => ({ withAttemptLock: vi.fn(async (operation) => operation()) }));

const storageKey = 'melorin:wallet-topup:s1:u1';
const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
const payment = (id) => json({ id, amount: 1000, currency: 'IRT', status: 'pending', instructions: {} });

function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function setup() {
  const requests = [];
  const notify = vi.fn();
  const coreFetch = vi.fn((path, options = {}) => {
    if (path.endsWith('/wallet/topups') && options.method === 'POST') {
      const request = { ...deferred(), key: options.headers['Idempotency-Key'] };
      requests.push(request);
      return request.promise;
    }
    if (path.endsWith('/receipt')) return Promise.resolve(json({ status: 'succeeded' }));
    return Promise.resolve(json([]));
  });
  const open = () =>
    render(<Wallet accountId="u1" coreFetch={coreFetch} storeId="s1" notify={notify} reload={() => {}} />);
  return { coreFetch, notify, open, requests };
}

async function start(view, amount) {
  const ui = within(view.container);
  await userEvent.type(ui.getByPlaceholderText('مبلغ'), amount);
  await userEvent.click(ui.getByRole('button', { name: 'ایجاد درخواست' }));
}

beforeEach(() => {
  localStorage.clear();
  vi.mocked(withAttemptLock)
    .mockReset()
    .mockImplementation(async (operation) => operation());
});

describe('wallet topup coordination', () => {
  it.each(['success', 'rejection'])('does not let a delayed %s overwrite a newer attempt', async (outcome) => {
    const { open, requests } = setup();
    const first = open();
    const retry = open();
    await start(first, '1000');
    await start(retry, '1000');
    await waitFor(() => expect(requests).toHaveLength(2));
    expect(requests[1].key).toBe(requests[0].key);

    await act(async () => requests[0].resolve(payment('p1')));
    await waitFor(() => expect(JSON.parse(localStorage.getItem(storageKey)).state).toBe('active'));
    const newer = open();
    await start(newer, '2000');
    await waitFor(() => expect(requests).toHaveLength(3));
    expect(requests[2].key).not.toBe(requests[0].key);

    await act(async () =>
      requests[1].resolve(outcome === 'success' ? payment('p1') : json({ error: { message: 'rejected' } }, 400)),
    );
    await waitFor(() => expect(JSON.parse(localStorage.getItem(storageKey))?.idempotencyKey).toBe(requests[2].key));
  });

  it('does not clear a newer attempt when an older receipt is confirmed', async () => {
    const { open, requests, notify } = setup();
    const first = open();
    await start(first, '1000');
    await waitFor(() => expect(requests).toHaveLength(1));
    await act(async () => requests[0].resolve(payment('p1')));
    const firstUi = within(first.container);
    await firstUi.findByRole('button', { name: 'ارسال رسید' });

    const newer = open();
    await start(newer, '2000');
    await waitFor(() => expect(requests).toHaveLength(2));
    const input = first.container.querySelector('input[type="file"]');
    await userEvent.upload(input, new File(['receipt'], 'receipt.png', { type: 'image/png' }));
    await userEvent.click(firstUi.getByRole('button', { name: 'ارسال رسید' }));
    await waitFor(() => expect(notify).toHaveBeenCalledWith(expect.stringContaining('تأیید شد')));
    expect(JSON.parse(localStorage.getItem(storageKey))?.idempotencyKey).toBe(requests[1].key);
  });

  it('does not send a topup when cross-tab coordination is unavailable', async () => {
    const { open, requests, notify } = setup();
    vi.mocked(withAttemptLock).mockRejectedValueOnce(new Error('storage unavailable'));
    await start(open(), '1000');
    await waitFor(() => expect(notify).toHaveBeenCalledWith(expect.stringContaining('ذخیره امن')));
    expect(requests).toHaveLength(0);
  });

  it('keeps an invalid success response unresolved and blocks a different amount', async () => {
    const { open, requests, notify } = setup();
    const view = open();
    await start(view, '1000');
    await waitFor(() => expect(requests).toHaveLength(1));
    await act(async () => requests[0].resolve(json({})));
    await waitFor(() => expect(notify).toHaveBeenCalledWith(expect.stringContaining('نتیجه درخواست شارژ مشخص نیست')));
    expect(JSON.parse(localStorage.getItem(storageKey)).state).toBe('unknown');

    const amount = within(view.container).getByPlaceholderText('مبلغ');
    await userEvent.clear(amount);
    await userEvent.type(amount, '2000');
    await userEvent.click(within(view.container).getByRole('button', { name: 'ایجاد درخواست' }));
    await waitFor(() => expect(notify).toHaveBeenCalledWith(expect.stringContaining('درخواست شارژ قبلی')));
    expect(requests).toHaveLength(1);
  });
});
