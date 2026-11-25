import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { listPendingOrders, submitOrder } from '../src/orderRequest.ts';
import * as attemptStorage from '../src/attemptLock.ts';
import { deleteAttemptDatabase, resetAttemptStorage } from './attemptStorage.js';

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
const body = { product_id: 'p1', payment_method: 'wallet', kind: 'purchase', bundle_id: 'b1' };
const input = (coreFetch, accountId = 'u1', order = body) => ({ coreFetch, storeId: 's1', accountId, body: order });
const keys = (mock) => mock.mock.calls.map(([, options]) => options.headers['Idempotency-Key']);

beforeEach(() => resetAttemptStorage());
afterEach(() => vi.restoreAllMocks());

describe('durable order requests', () => {
  it('reuses the key after an uncertain response and a later retry', async () => {
    const coreFetch = vi
      .fn()
      .mockResolvedValueOnce(json({ error: {} }, 503))
      .mockResolvedValueOnce(json({ id: 'o1' }));
    expect((await submitOrder(input(coreFetch))).response.ok).toBe(false);
    expect((await submitOrder(input(coreFetch))).order.id).toBe('o1');
    expect(keys(coreFetch)[1]).toBe(keys(coreFetch)[0]);
  });

  it('retains the key when the connection or a successful response body is lost', async () => {
    const coreFetch = vi
      .fn()
      .mockRejectedValueOnce(new Error('connection lost'))
      .mockResolvedValueOnce(new Response('invalid json', { status: 200 }))
      .mockResolvedValueOnce(json({ id: 'o1' }));
    await expect(submitOrder(input(coreFetch))).rejects.toThrow('نتیجه سفارش مشخص نیست');
    await expect(submitOrder(input(coreFetch))).rejects.toThrow('نتیجه سفارش مشخص نیست');
    await submitOrder(input(coreFetch));
    expect(new Set(keys(coreFetch)).size).toBe(1);
  });

  it('keeps pending keys separate by account and request', async () => {
    const coreFetch = vi.fn(async () => json({}, 503));
    await submitOrder(input(coreFetch, 'u1'));
    await submitOrder(input(coreFetch, 'u2'));
    await submitOrder(input(coreFetch, 'u1', { ...body, product_id: 'p2' }));
    await submitOrder(input(coreFetch, 'u1'));
    expect(new Set(keys(coreFetch).slice(0, 3)).size).toBe(3);
    expect(keys(coreFetch)[3]).toBe(keys(coreFetch)[0]);
  });

  it('uses a fresh key for a new order after a confirmed success', async () => {
    const coreFetch = vi.fn(async () => json({ id: 'o1' }));
    await submitOrder(input(coreFetch));
    await submitOrder(input(coreFetch));
    expect(keys(coreFetch)[1]).not.toBe(keys(coreFetch)[0]);
  });

  it('keeps a newer pending key when a duplicate response arrives late', async () => {
    const pending = [];
    const coreFetch = vi.fn(() => new Promise((resolve) => pending.push(resolve)));
    const first = submitOrder(input(coreFetch));
    const duplicate = submitOrder(input(coreFetch));
    await vi.waitFor(() => expect(pending).toHaveLength(2));
    expect(keys(coreFetch)[0]).toBe(keys(coreFetch)[1]);

    pending[0](json({ id: 'old' }));
    await first;
    const next = submitOrder(input(coreFetch));
    await vi.waitFor(() => expect(pending).toHaveLength(3));
    expect(keys(coreFetch)[2]).not.toBe(keys(coreFetch)[0]);
    pending[1](json({ id: 'old' }));
    await duplicate;
    pending[2](json({}, 503));
    await next;
    const retry = submitOrder(input(coreFetch));
    await vi.waitFor(() => expect(pending).toHaveLength(4));
    expect(keys(coreFetch)[3]).toBe(keys(coreFetch)[2]);
    pending[3](json({ id: 'new' }));
    await retry;
  });

  it('finds pending orders only for the current store, account and kind', async () => {
    const coreFetch = vi.fn(async () => json({}, 503));
    const renewal = { product_id: 'p1', payment_method: 'wallet', kind: 'renewal', vpn_account_id: 'vpn1' };
    await submitOrder(input(coreFetch, 'u1', renewal));
    await submitOrder(input(coreFetch, 'u1', body));
    expect(await listPendingOrders('renewal', 's1', 'u1')).toEqual([{ body: renewal, key: keys(coreFetch)[0] }]);
    expect(await listPendingOrders('purchase', 's1', 'u1')).toEqual([{ body, key: keys(coreFetch)[1] }]);
    expect(await listPendingOrders('renewal', 's1', 'u2')).toEqual([]);
    expect(await listPendingOrders('purchase', 's1', 'u2')).toEqual([]);
    expect(await listPendingOrders('renewal', 's2', 'u1')).toEqual([]);
  });

  it('does not resubmit a stale recovery action after another tab confirmed it', async () => {
    const coreFetch = vi
      .fn()
      .mockResolvedValueOnce(json({}, 503))
      .mockResolvedValueOnce(json({ id: 'o1' }));
    const renewal = { product_id: 'p1', payment_method: 'wallet', kind: 'renewal', vpn_account_id: 'vpn1' };
    await submitOrder(input(coreFetch, 'u1', renewal));
    const [attempt] = await listPendingOrders('renewal', 's1', 'u1');
    await submitOrder(input(coreFetch, 'u1', renewal));
    await expect(submitOrder({ ...input(coreFetch, 'u1', renewal), expectedKey: attempt.key })).rejects.toThrow(
      'وضعیت درخواست قبلی تغییر کرده است',
    );
    expect(coreFetch).toHaveBeenCalledTimes(2);
  });

  it('does not send if cross-tab storage coordination is unavailable', async () => {
    const coreFetch = vi.fn();
    vi.spyOn(attemptStorage, 'updateStoredAttempt').mockRejectedValueOnce(new Error('blocked'));
    await expect(submitOrder(input(coreFetch))).rejects.toThrow('درخواست ارسال نشد');
    expect(coreFetch).not.toHaveBeenCalled();
  });

  it('does not send without an account or when safe storage is unavailable', async () => {
    const coreFetch = vi.fn();
    await expect(submitOrder(input(coreFetch, ''))).rejects.toThrow('اطلاعات حساب');
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    await expect(submitOrder(input(coreFetch))).rejects.toThrow('درخواست ارسال نشد');
    expect(coreFetch).not.toHaveBeenCalled();
  });

  it('migrates a legacy pending order and keeps using its original key', async () => {
    const storageKey = 'melorin:order-attempt:s1:u1:' + encodeURIComponent(JSON.stringify(body));
    const legacyKey = 'web-order-11111111-1111-4111-8111-111111111111';
    localStorage.setItem(storageKey, legacyKey);
    const coreFetch = vi.fn(async () => json({}, 503));
    await submitOrder(input(coreFetch));
    expect(keys(coreFetch)).toEqual([legacyKey]);
    expect(await listPendingOrders('purchase', 's1', 'u1')).toEqual([{ body, key: legacyKey }]);

    // Stale legacy data must never replace the authoritative IndexedDB value.
    localStorage.setItem(storageKey, 'web-order-22222222-2222-4222-8222-222222222222');
    await submitOrder(input(coreFetch));
    expect(keys(coreFetch)[1]).toBe(legacyKey);
  });

  it('does not send a new order if its initialized IndexedDB was deleted', async () => {
    const coreFetch = vi.fn(async () => json({}, 503));
    await submitOrder(input(coreFetch));
    await deleteAttemptDatabase();
    await expect(submitOrder(input(coreFetch))).rejects.toThrow('درخواست ارسال نشد');
    await expect(listPendingOrders('purchase', 's1', 'u1')).rejects.toThrow('attempt storage lost');
    expect(coreFetch).toHaveBeenCalledTimes(1);
  });

  it('prevents an older tab from reopening the legacy database version', async () => {
    await submitOrder(input(vi.fn(async () => json({}, 503))));
    const oldVersion = new Promise((resolve, reject) => {
      const request = indexedDB.open('melorin-attempt-lock', 1);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    await expect(oldVersion).rejects.toHaveProperty('name', 'VersionError');
  });

  it('does not hide a corrupted pending order from recovery', async () => {
    localStorage.setItem('melorin:order-attempt:s1:u1:%broken', 'web-order-1111');
    await expect(listPendingOrders('purchase', 's1', 'u1')).rejects.toThrow();
  });
});
