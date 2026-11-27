// Data hooks shared by the tabs of the payments hub (PaymentsView). Each tab used to fetch its own copy of the same
// resources, or worse, the old single screen fetched everything at once; now the hub owns them and the tabs only read.
import { useCallback, useEffect, useMemo, useState } from 'react';
import { API_BASE, typedClient } from '../../api/api.ts';
import type { CallFn } from '../../shared/types.ts';
import type { PaymentRow } from './paymentsShared.tsx';

const isAbort = (e: unknown) => e instanceof DOMException && e.name === 'AbortError';

/** The main store's id: `null` while resolving, `false` when the installation has no main store. */
export function useMainStore(): string | false | null {
  const client = useMemo(() => typedClient(API_BASE), []);
  const [store, setStore] = useState<string | false | null>(null);
  useEffect(() => {
    const ctl = new AbortController();
    client
      .get('/api/v1/me/stores', { signal: ctl.signal })
      .then(({ data, response }) => {
        const stores = (response.ok && Array.isArray(data) ? data : []) as { id?: string; kind?: string }[];
        setStore(stores.find((x) => x.kind === 'main')?.id || false);
      })
      .catch((e) => !isAbort(e) && setStore(false));
    return () => ctl.abort();
  }, [client]);
  return store;
}

/** GET /api/v1/admin/payments once, with a manual `reload`. `rows` stays `null` until the first answer. */
export function usePayments(base?: string) {
  const client = useMemo(() => typedClient(base ?? API_BASE), [base]);
  const [rows, setRows] = useState<PaymentRow[] | null>(null);
  const [failed, setFailed] = useState(false);
  const reload = useCallback(async () => {
    try {
      const { data, response } = await client.get('/api/v1/admin/payments');
      if (!response.ok) throw new Error(String(response.status));
      const list = Array.isArray(data) ? data : (data as { items?: unknown[] } | undefined)?.items;
      setRows((list ?? []) as PaymentRow[]);
      setFailed(false);
    } catch {
      setFailed(true);
      setRows((x) => x || []);
    }
  }, [client]);
  useEffect(() => {
    reload();
  }, [reload]);
  return { client, rows, failed, reload };
}

/**
 * How many provisional (temporarily approved) charges wait for a final decision. This feeds the badge on the receipts
 * tab, so an urgent item is visible from any tab; it is silent on failure (an older server has no such endpoint).
 */
export function useProvisionalCount(call: CallFn, store: string | false | null, everyMs = 30000) {
  const [count, setCount] = useState(0);
  const refresh = useCallback(async () => {
    if (!store) return;
    try {
      const r = await call(`/api/v1/admin/stores/${store}/receipt-review`);
      if (!r.ok) return;
      const d = await r.json();
      setCount(Array.isArray(d?.provisional) ? d.provisional.length : 0);
    } catch {
      /* transient: the next tick retries */
    }
  }, [call, store]);
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, everyMs);
    return () => clearInterval(t);
  }, [refresh, everyMs]);
  return { count, refresh };
}
