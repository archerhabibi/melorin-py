import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import Loyalty from '../src/Loyalty.tsx';
import * as attemptStorage from '../src/attemptLock.ts';
import { readAttempt, resetAttemptStorage } from './attemptStorage.js';

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
const reward = { id: 'r1', name: 'پاداش', cost_points: 100, value: 1000, available: true };
const club = (rewards = [reward]) => ({
  enabled: true,
  currency: 'IRT',
  balance: 1000,
  lifetime_earned: 1000,
  debt: 0,
  rewards,
  history: [],
});

beforeEach(() => {
  vi.restoreAllMocks();
  resetAttemptStorage();
});

it('reuses the redemption key after an ambiguous server error', async () => {
  const keys = [];
  const coreFetch = vi.fn(async (_path, options) => {
    if (options?.method === 'POST') {
      keys.push(options.headers['Idempotency-Key']);
      return keys.length === 1 ? json({ error: { message: 'نامعلوم' } }, 503) : json({ id: 'redeem-1' });
    }
    return json(club());
  });
  const notify = vi.fn();
  render(<Loyalty coreFetch={coreFetch} storeId="s1" accountId="u1" notify={notify} />);
  await userEvent.click(await screen.findByRole('button', { name: 'دریافت پاداش' }));
  await waitFor(() => expect(notify).toHaveBeenCalledWith('نامعلوم'));
  const retry =
    screen.queryByRole('button', { name: 'پیگیری پاداش' }) || screen.getByRole('button', { name: 'دریافت پاداش' });
  await userEvent.click(retry);
  await waitFor(() => expect(keys).toHaveLength(2));
  expect(keys[1]).toBe(keys[0]);
});

it('recovers the same reward after reload even if it is no longer listed', async () => {
  const keys = [];
  const coreFetch = vi.fn(async (_path, options) => {
    if (options?.method === 'POST') {
      keys.push(options.headers['Idempotency-Key']);
      return keys.length === 1 ? json({ error: { message: 'نامعلوم' } }, 503) : json({ id: 'redeem-1' });
    }
    return json(club(keys.length ? [] : [reward]));
  });
  const notify = vi.fn();
  const first = render(<Loyalty coreFetch={coreFetch} storeId="s1" accountId="u1" notify={notify} />);
  await userEvent.click(await screen.findByRole('button', { name: 'دریافت پاداش' }));
  await waitFor(() => expect(notify).toHaveBeenCalledWith('نامعلوم'));
  first.unmount();
  render(<Loyalty coreFetch={coreFetch} storeId="s1" accountId="u1" notify={notify} />);
  await userEvent.click(await screen.findByRole('button', { name: 'پیگیری پاداش' }));
  await waitFor(() => expect(keys).toHaveLength(2));
  expect(keys[1]).toBe(keys[0]);
});

it('migrates a pending reward and keeps its original key after reload', async () => {
  const storageKey = 'melorin:loyalty-redemption:s1:u1:r1';
  const key = 'legacy-reward-key';
  localStorage.setItem(storageKey, JSON.stringify({ name: 'پاداش', key }));
  const keys = [];
  const coreFetch = vi.fn(async (_path, options) => {
    if (options?.method === 'POST') {
      keys.push(options.headers['Idempotency-Key']);
      return json({ error: { message: 'نامعلوم' } }, 503);
    }
    return json(club([]));
  });
  const open = () => render(<Loyalty coreFetch={coreFetch} storeId="s1" accountId="u1" notify={vi.fn()} />);
  const first = open();
  await userEvent.click(await screen.findByRole('button', { name: 'پیگیری پاداش' }));
  await waitFor(() => expect(keys).toEqual([key]));
  first.unmount();
  localStorage.setItem(storageKey, JSON.stringify({ name: 'پاداش', key: 'stale-other-key' }));
  open();
  await userEvent.click(await screen.findByRole('button', { name: 'پیگیری پاداش' }));
  await waitFor(() => expect(keys).toEqual([key, key]));
  expect(JSON.parse(await readAttempt(storageKey)).key).toBe(key);
});

it('does not show one customer the unresolved rewards of another customer', async () => {
  const coreFetch = vi.fn(async (_path, options) =>
    options?.method === 'POST' ? json({ error: { message: 'نامعلوم' } }, 503) : json(club()),
  );
  const notify = vi.fn();
  const first = render(<Loyalty coreFetch={coreFetch} storeId="s1" accountId="u1" notify={notify} />);
  await userEvent.click(await screen.findByRole('button', { name: 'دریافت پاداش' }));
  await waitFor(() => expect(notify).toHaveBeenCalledWith('نامعلوم'));
  first.unmount();
  render(<Loyalty coreFetch={coreFetch} storeId="s1" accountId="u2" notify={notify} />);
  expect(await screen.findByRole('button', { name: 'دریافت پاداش' })).toBeEnabled();
  expect(screen.queryByRole('button', { name: 'پیگیری پاداش' })).not.toBeInTheDocument();
});

it('does not allow redemption before the customer identity is available', async () => {
  const coreFetch = vi.fn(async () => json(club()));
  render(<Loyalty coreFetch={coreFetch} storeId="s1" notify={vi.fn()} />);
  expect(await screen.findByRole('button', { name: 'دریافت پاداش' })).toBeDisabled();
});

it('does not erase a newer redemption when an old response arrives late', async () => {
  const requests = [];
  const coreFetch = vi.fn((_path, options) => {
    if (options?.method !== 'POST') return Promise.resolve(json(club()));
    let resolve;
    const promise = new Promise((done) => {
      resolve = done;
    });
    requests.push({ key: options.headers['Idempotency-Key'], resolve });
    return promise;
  });
  const open = () => render(<Loyalty coreFetch={coreFetch} storeId="s1" accountId="u1" notify={vi.fn()} />);
  const first = open();
  const retry = open();
  for (const view of [first, retry]) {
    const button = await within(view.container).findByRole('button', { name: 'دریافت پاداش' });
    await waitFor(() => expect(button).toBeEnabled());
    await userEvent.click(button);
  }
  await waitFor(() => expect(requests).toHaveLength(2));
  expect(requests[1].key).toBe(requests[0].key);
  const storageKey = 'melorin:loyalty-redemption:s1:u1:r1';
  await act(async () => requests[0].resolve(json({ id: 'old-redemption' })));
  await waitFor(async () => expect(await readAttempt(storageKey)).toBeNull());

  const newer = open();
  const button = await within(newer.container).findByRole('button', { name: 'دریافت پاداش' });
  await waitFor(() => expect(button).toBeEnabled());
  await userEvent.click(button);
  await waitFor(() => expect(requests).toHaveLength(3));
  expect(requests[2].key).not.toBe(requests[0].key);
  await act(async () => requests[1].resolve(json({ id: 'old-redemption' })));
  expect(JSON.parse(await readAttempt(storageKey)).key).toBe(requests[2].key);
});

it('keeps a malformed success unresolved and reuses its key', async () => {
  const keys = [];
  const coreFetch = vi.fn(async (_path, options) => {
    if (options?.method === 'POST') {
      keys.push(options.headers['Idempotency-Key']);
      return keys.length === 1 ? json({}) : json({ id: 'redeem-1' });
    }
    return json(club());
  });
  const notify = vi.fn();
  render(<Loyalty coreFetch={coreFetch} storeId="s1" accountId="u1" notify={notify} />);
  await userEvent.click(await screen.findByRole('button', { name: 'دریافت پاداش' }));
  await waitFor(() => expect(notify).toHaveBeenCalledWith(expect.stringContaining('نتیجه درخواست پاداش مشخص نیست')));
  await userEvent.click(await screen.findByRole('button', { name: 'پیگیری پاداش' }));
  await waitFor(() => expect(keys).toHaveLength(2));
  expect(keys[1]).toBe(keys[0]);
});

it('refuses a redemption if cross-tab coordination is unavailable', async () => {
  const coreFetch = vi.fn(async () => json(club()));
  const notify = vi.fn();
  render(<Loyalty coreFetch={coreFetch} storeId="s1" accountId="u1" notify={notify} />);
  const button = await screen.findByRole('button', { name: 'دریافت پاداش' });
  await waitFor(() => expect(button).toBeEnabled());
  vi.spyOn(attemptStorage, 'updateStoredAttempt').mockRejectedValueOnce(new Error('storage unavailable'));
  await userEvent.click(button);
  await waitFor(() => expect(notify).toHaveBeenCalledWith(expect.stringContaining('ذخیره امن')));
  expect(coreFetch.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(0);
});
