import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Wallet } from '../src/dashboard/DashboardWallet.tsx';
import * as attemptStorage from '../src/attemptLock.ts';
import { deleteAttemptDatabase, readAttempt, resetAttemptStorage, writeAttempt } from './attemptStorage.js';

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
const storageKey = 'melorin:wallet-topup:s1:u1';
const newer = { amount: '2000', idempotencyKey: 'topup-22222222-2222-4222-8222-222222222222', state: 'unknown' };

beforeEach(() => {
  vi.restoreAllMocks();
  resetAttemptStorage();
});

describe('wallet topup retry safety', () => {
  it.each([
    ['a rejected request', () => json({ error: { code: 'BAD_INPUT', message: 'رد شد' } }, 400)],
    ['a cancelled payment', () => json({ id: 'old', status: 'cancelled', amount: 1000, instructions: {} })],
    ['a successful response', () => json({ id: 'old', status: 'pending', amount: 1000, instructions: {} })],
  ])('keeps a newer pending attempt when %s arrives late', async (_scenario, response) => {
    let finish;
    const notify = vi.fn();
    const coreFetch = vi.fn((path) => {
      if (path.endsWith('/wallet/transactions')) return Promise.resolve(json([]));
      return new Promise((resolve) => {
        finish = resolve;
      });
    });
    render(<Wallet accountId="u1" storeId="s1" coreFetch={coreFetch} notify={notify} reload={() => {}} />);
    await userEvent.type(screen.getByPlaceholderText('مبلغ'), '1000');
    await userEvent.click(screen.getByRole('button', { name: 'ایجاد درخواست' }));
    await waitFor(() => expect(finish).toBeTypeOf('function'));

    // Another tab started a newer attempt while the first HTTP response was delayed.
    await writeAttempt(storageKey, JSON.stringify(newer));
    await act(async () => finish(response()));

    expect(JSON.parse(await readAttempt(storageKey))).toEqual(newer);
  });

  it('does not send a topup if cross-tab coordination is unavailable', async () => {
    vi.spyOn(attemptStorage, 'updateStoredAttempt').mockRejectedValueOnce(new Error('blocked'));
    const notify = vi.fn();
    const coreFetch = vi.fn(async () => json([]));
    render(<Wallet accountId="u1" storeId="s1" coreFetch={coreFetch} notify={notify} reload={() => {}} />);
    await userEvent.type(screen.getByPlaceholderText('مبلغ'), '1000');
    await userEvent.click(screen.getByRole('button', { name: 'ایجاد درخواست' }));
    await waitFor(() => expect(notify).toHaveBeenCalledWith(expect.stringContaining('درخواست ارسال نشد')));
    expect(
      coreFetch.mock.calls.some(([path, options]) => path.endsWith('/wallet/topups') && options?.method === 'POST'),
    ).toBe(false);
  });

  it('keeps the shared key after one tab receives a 4xx while another request is in flight', async () => {
    const pending = [];
    const keys = [];
    const coreFetch = vi.fn((path, options = {}) => {
      if (path.endsWith('/wallet/transactions')) return Promise.resolve(json([]));
      keys.push(options.headers['Idempotency-Key']);
      return new Promise((resolve) => pending.push(resolve));
    });
    const first = render(
      <Wallet accountId="u1" storeId="s1" coreFetch={coreFetch} notify={() => {}} reload={() => {}} />,
    );
    const second = render(
      <Wallet accountId="u1" storeId="s1" coreFetch={coreFetch} notify={() => {}} reload={() => {}} />,
    );
    for (const container of [first.container, second.container]) {
      await userEvent.type(within(container).getByPlaceholderText('مبلغ'), '1000');
      await userEvent.click(within(container).getByRole('button', { name: 'ایجاد درخواست' }));
    }
    await waitFor(() => expect(pending).toHaveLength(2));
    expect(keys[0]).toBe(keys[1]);
    await act(async () => pending[1](json({ error: { message: 'رد شد' } }, 400)));
    expect(JSON.parse(await readAttempt(storageKey)).idempotencyKey).toBe(keys[0]);
    await act(async () => pending[0](json({ id: 'p1', status: 'pending', amount: 1000, instructions: {} })));
  });

  it('keeps the request unresolved when a successful response has no payment identity', async () => {
    const notify = vi.fn();
    const coreFetch = vi.fn(async (path) =>
      path.endsWith('/wallet/transactions') ? json([]) : json({ status: 'pending' }),
    );
    render(<Wallet accountId="u1" storeId="s1" coreFetch={coreFetch} notify={notify} reload={() => {}} />);
    await userEvent.type(screen.getByPlaceholderText('مبلغ'), '1000');
    await userEvent.click(screen.getByRole('button', { name: 'ایجاد درخواست' }));
    await waitFor(() => expect(notify).toHaveBeenCalledWith(expect.stringContaining('نتیجهٔ درخواست شارژ مشخص نیست')));
    expect(JSON.parse(await readAttempt(storageKey)).state).toBe('unknown');
  });

  it('does not forget a previously confirmed payment when its retry receives an error', async () => {
    const active = { ...newer, amount: '1000', state: 'active' };
    localStorage.setItem(storageKey, JSON.stringify(active));
    const notify = vi.fn();
    const coreFetch = vi.fn(async (path) =>
      path.endsWith('/wallet/transactions') ? json([]) : json({ error: { message: 'نامعلوم' } }, 503),
    );
    render(<Wallet accountId="u1" storeId="s1" coreFetch={coreFetch} notify={notify} reload={() => {}} />);
    await userEvent.type(screen.getByPlaceholderText('مبلغ'), '1000');
    await userEvent.click(screen.getByRole('button', { name: 'ایجاد درخواست' }));
    await waitFor(() => expect(notify).toHaveBeenCalledWith('نامعلوم'));
    expect(JSON.parse(await readAttempt(storageKey))).toEqual(active);
  });

  it('migrates a legacy unresolved topup and reuses its key', async () => {
    const legacy = { ...newer, amount: '1000' };
    localStorage.setItem(storageKey, JSON.stringify(legacy));
    const keys = [];
    const notify = vi.fn();
    const coreFetch = vi.fn(async (path, options = {}) => {
      if (path.endsWith('/wallet/transactions')) return json([]);
      keys.push(options.headers['Idempotency-Key']);
      return json({ error: { message: 'نامعلوم' } }, 503);
    });
    render(<Wallet accountId="u1" storeId="s1" coreFetch={coreFetch} notify={notify} reload={() => {}} />);
    await userEvent.type(screen.getByPlaceholderText('مبلغ'), '1000');
    await userEvent.click(screen.getByRole('button', { name: 'ایجاد درخواست' }));
    await waitFor(() => expect(notify).toHaveBeenCalledWith('نامعلوم'));
    expect(keys).toEqual([legacy.idempotencyKey]);
    expect(JSON.parse(await readAttempt(storageKey))).toEqual(legacy);
  });

  it('does not create another payment when initialized IndexedDB was deleted', async () => {
    const keys = [];
    const notify = vi.fn();
    const coreFetch = vi.fn(async (path, options = {}) => {
      if (path.endsWith('/wallet/transactions')) return json([]);
      keys.push(options.headers['Idempotency-Key']);
      return json({ error: { message: 'نامعلوم' } }, 503);
    });
    render(<Wallet accountId="u1" storeId="s1" coreFetch={coreFetch} notify={notify} reload={() => {}} />);
    await userEvent.type(screen.getByPlaceholderText('مبلغ'), '1000');
    await userEvent.click(screen.getByRole('button', { name: 'ایجاد درخواست' }));
    await waitFor(() => expect(notify).toHaveBeenCalledWith('نامعلوم'));
    await deleteAttemptDatabase();
    await userEvent.click(screen.getByRole('button', { name: 'ایجاد درخواست' }));
    await waitFor(() => expect(notify).toHaveBeenCalledWith(expect.stringContaining('درخواست ارسال نشد')));
    expect(keys).toHaveLength(1);
  });

  it('does not remove a newer attempt when an older payment receipt completes', async () => {
    const coreFetch = vi.fn(async (path) => {
      if (path.endsWith('/wallet/transactions')) return json([]);
      if (path.endsWith('/wallet/topups'))
        return json({ id: 'old', status: 'pending', amount: 1000, instructions: {} });
      if (path.endsWith('/receipt')) return json({ status: 'succeeded' });
      return json([]);
    });
    const notify = vi.fn();
    render(<Wallet accountId="u1" storeId="s1" coreFetch={coreFetch} notify={notify} reload={() => {}} />);
    await userEvent.type(screen.getByPlaceholderText('مبلغ'), '1000');
    await userEvent.click(screen.getByRole('button', { name: 'ایجاد درخواست' }));
    await screen.findByRole('button', { name: 'ارسال رسید' });
    await writeAttempt(storageKey, JSON.stringify(newer));

    await userEvent.upload(
      screen.getByLabelText('انتخاب تصویر رسید'),
      new File(['receipt'], 'receipt.png', { type: 'image/png' }),
    );
    await userEvent.click(screen.getByRole('button', { name: 'ارسال رسید' }));
    await waitFor(() => expect(notify).toHaveBeenCalledWith(expect.stringContaining('شارژ شد')));
    expect(JSON.parse(await readAttempt(storageKey))).toEqual(newer);
  });
});
