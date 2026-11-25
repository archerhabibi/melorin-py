import { listStoredAttempts, updateStoredAttempt } from './attemptLock.ts';

type OrderRequest = {
  coreFetch: (path: string, options: RequestInit) => Promise<Response>;
  storeId?: string;
  accountId?: string;
  body: Record<string, unknown>;
  expectedKey?: string;
};

type Order = { id: string };

export type OrderKind = 'purchase' | 'renewal';
export type PendingOrder = { body: Record<string, unknown>; key: string };

function attemptPrefix(storeId: string, accountId: string) {
  return 'melorin:order-attempt:' + encodeURIComponent(storeId) + ':' + encodeURIComponent(accountId) + ':';
}

/** Find unresolved orders even if a fresh quote is unavailable. */
export async function listPendingOrders(
  kind: OrderKind,
  storeId?: string,
  accountId?: string,
): Promise<PendingOrder[]> {
  if (!storeId?.trim() || !accountId?.trim()) return [];
  const prefix = attemptPrefix(storeId, accountId);
  const attempts: PendingOrder[] = [];
  for (const [storageKey, key] of await listStoredAttempts(prefix)) {
    const body: Record<string, unknown> = JSON.parse(decodeURIComponent(storageKey.slice(prefix.length)));
    if (!body || typeof body !== 'object' || Array.isArray(body) || !/^web-order-[0-9a-f-]+$/i.test(key))
      throw new Error('invalid stored attempt');
    if (body.kind !== kind || body.payment_method !== 'wallet') continue;
    if (typeof body.product_id !== 'string' || (kind === 'renewal' && typeof body.vpn_account_id !== 'string'))
      throw new Error('invalid stored attempt');
    attempts.push({ body, key });
  }
  return attempts;
}

/** Preserve one request key until its result is known, including across reloads. */
export async function submitOrder({ coreFetch, storeId, accountId, body, expectedKey }: OrderRequest) {
  if (!storeId?.trim() || !accountId?.trim()) {
    throw new Error('برای ثبت سفارش، اطلاعات حساب باید بارگذاری شود.');
  }
  const payload = JSON.stringify(body);
  const storageKey = attemptPrefix(storeId, accountId) + encodeURIComponent(payload);
  let key: string | null;
  try {
    key = await updateStoredAttempt(storageKey, (saved) => {
      if (expectedKey && saved !== expectedKey) return { result: null };
      if (saved && !/^web-order-[0-9a-f-]+$/i.test(saved)) throw new Error('invalid stored key');
      const current = saved || 'web-order-' + crypto.randomUUID();
      return { value: current, result: current };
    });
  } catch {
    throw new Error('ذخیره امن وضعیت سفارش ممکن نیست؛ درخواست ارسال نشد.');
  }

  if (!key) throw new Error('وضعیت درخواست قبلی تغییر کرده است؛ سفارش‌ها را دوباره بررسی کنید.');

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
    await updateStoredAttempt(storageKey, (saved) => {
      // A delayed response must never clear a newer attempt in another tab.
      return saved === key ? { value: null, result: undefined } : { result: undefined };
    });
  } catch {
    // Keeping a confirmed key is safer than accidentally repeating the order.
  }
  return { response, order };
}
