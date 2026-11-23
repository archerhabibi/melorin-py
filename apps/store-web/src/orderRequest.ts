import { withAttemptLock } from './attemptLock.ts';

type OrderRequest = {
  coreFetch: (path: string, options: RequestInit) => Promise<Response>;
  storeId?: string;
  accountId?: string;
  body: Record<string, unknown>;
};

type Order = { id: string };

/** Preserve one request key until its result is known, including across reloads. */
export async function submitOrder({ coreFetch, storeId, accountId, body }: OrderRequest) {
  if (!storeId?.trim() || !accountId?.trim()) {
    throw new Error('برای ثبت سفارش، اطلاعات حساب باید بارگذاری شود.');
  }
  const payload = JSON.stringify(body);
  const storageKey =
    'melorin:order-attempt:' +
    encodeURIComponent(storeId) +
    ':' +
    encodeURIComponent(accountId) +
    ':' +
    encodeURIComponent(payload);
  let key: string;
  try {
    key = await withAttemptLock(() => {
      const saved = localStorage.getItem(storageKey);
      if (saved && !/^web-order-[0-9a-f-]+$/i.test(saved)) throw new Error('invalid stored key');
      const current = saved || 'web-order-' + crypto.randomUUID();
      localStorage.setItem(storageKey, current);
      return current;
    });
  } catch {
    throw new Error('ذخیره امن وضعیت سفارش ممکن نیست؛ درخواست ارسال نشد.');
  }

  let response: Response;
  try {
    response = await coreFetch('/api/v1/stores/' + encodeURIComponent(storeId) + '/orders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key },
      body: payload,
    });
  } catch {
    throw new Error('نتیجه سفارش مشخص نیست. برای جلوگیری از خرید تکراری، همین سفارش را دوباره بررسی کنید.');
  }
  if (!response.ok) return { response, order: null };

  let order: Order;
  try {
    order = (await response.json()) as Order;
    if (!order || typeof order.id !== 'string' || !order.id) throw new Error('missing order id');
  } catch {
    throw new Error('نتیجه سفارش مشخص نیست. برای جلوگیری از خرید تکراری، همین سفارش را دوباره بررسی کنید.');
  }
  try {
    await withAttemptLock(() => {
      // A delayed response must never clear a newer attempt in another tab.
      if (localStorage.getItem(storageKey) === key) localStorage.removeItem(storageKey);
    });
  } catch {
    // Keeping a confirmed key is safer than accidentally repeating the order.
  }
  return { response, order };
}
