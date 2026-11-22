import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { typedClient } from '../../api/api.ts';
import type { Toast } from '../../shared/types.ts';
import type { CouponRow } from './couponForm.ts';

export interface StoreOption {
  id: string;
  name: string;
  kind: string;
  currency: string;
}

/**
 * Stores + the coupon list of the selected store, both through the typed client.
 *
 * `storeId`: null = still resolving the default, '' = every store (also multi-store codes).
 * The coupon request waits for that choice (one request, not an "all" request followed by a filtered one) and a
 * response that arrives after the admin already switched store is dropped, never shown.
 */
export function useCoupons(base: string | undefined, toast: Toast) {
  const client = useMemo(() => typedClient(base ?? ''), [base]);
  const [stores, setStores] = useState<StoreOption[]>([]);
  const [storeId, setStoreId] = useState<string | null>(null);
  const [rows, setRows] = useState<CouponRow[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((n) => n + 1), []);
  const notify = useRef(toast); // the effects below must not re-run (and refetch) just because the parent re-rendered
  useEffect(() => {
    notify.current = toast;
  });

  useEffect(() => {
    let alive = true;
    client
      .get('/api/v1/admin/stores')
      .then(({ data, response }) => {
        if (!alive) return;
        if (!response.ok) throw new Error(String(response.status));
        const list = ((data ?? []) as Record<string, unknown>[]).map((s) => ({
          id: String(s.id),
          name: String(s.name ?? ''),
          kind: String(s.kind ?? ''),
          currency: String(s.currency ?? ''),
        }));
        setStores(list);
        // a discount code belongs to ONE store: default to the main store
        setStoreId((cur) => cur ?? (list.find((s) => s.kind === 'main') ?? list[0])?.id ?? '');
      })
      .catch(() => {
        if (!alive) return;
        notify.current('دریافت فهرست فروشگاه‌ها ناموفق بود');
        setStoreId((cur) => cur ?? '');
      });
    return () => {
      alive = false;
    };
  }, [client]);

  useEffect(() => {
    if (storeId === null) return;
    const ctl = new AbortController();
    setFailed(false);
    client
      .get('/api/v1/admin/coupons', { params: { query: storeId ? { store_id: storeId } : {} }, signal: ctl.signal })
      .then(({ data, response }) => {
        if (ctl.signal.aborted) return;
        if (!response.ok) throw new Error(String(response.status));
        setRows(data ?? []);
      })
      .catch(() => {
        if (!ctl.signal.aborted) setFailed(true);
      });
    return () => ctl.abort();
  }, [client, storeId, tick]);

  return { client, stores, storeId, setStoreId, rows, failed, reload };
}
