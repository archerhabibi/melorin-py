import { useCallback, useEffect, useState } from 'react';
import { listPendingOrders } from './orderRequest.ts';
import { subscribeToAttemptChanges } from './attemptLock.ts';
import type { OrderKind, PendingOrder } from './orderRequest.ts';

/** Keep recovery views scoped to the current account and in sync with other tabs. */
export function usePendingOrders(kind: OrderKind, storeId?: string, accountId?: string) {
  const scope = JSON.stringify([kind, storeId, accountId]);
  const [version, setVersion] = useState(0);
  const [snapshot, setSnapshot] = useState<{ scope: string; attempts: PendingOrder[]; error: boolean } | null>(null);
  const refresh = useCallback(() => {
    setSnapshot(null);
    setVersion((current) => current + 1);
  }, []);
  useEffect(() => {
    let live = true;
    listPendingOrders(kind, storeId, accountId)
      .then((attempts) => live && setSnapshot({ scope, attempts, error: false }))
      .catch(() => live && setSnapshot({ scope, attempts: [], error: true }));
    return () => {
      live = false;
    };
  }, [kind, storeId, accountId, scope, version]);
  useEffect(() => {
    return subscribeToAttemptChanges((key) => {
      if (key === null || key.startsWith('melorin:order-attempt:')) refresh();
    });
  }, [refresh]);
  const current = snapshot?.scope === scope ? snapshot : null;
  return {
    attempts: current?.attempts || [],
    ready: !!current && !current.error,
    error: current?.error || false,
    refresh,
  };
}
