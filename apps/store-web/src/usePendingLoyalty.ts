import { useCallback, useEffect, useState } from 'react';
import { listPendingRewards } from './loyaltyAttempts.ts';
import type { PendingReward } from './loyaltyAttempts.ts';

export function usePendingLoyalty(storeId?: string, accountId?: string) {
  const scope = JSON.stringify([storeId, accountId]);
  const [version, setVersion] = useState(0);
  const [snapshot, setSnapshot] = useState<{ scope: string; attempts: PendingReward[]; error: boolean } | null>(null);
  const refresh = useCallback(() => {
    setSnapshot(null);
    setVersion((current) => current + 1);
  }, []);
  useEffect(() => {
    let live = true;
    if (storeId?.trim() && accountId?.trim()) {
      listPendingRewards(storeId, accountId)
        .then((attempts) => live && setSnapshot({ scope, attempts, error: false }))
        .catch(() => live && setSnapshot({ scope, attempts: [], error: true }));
    }
    return () => {
      live = false;
    };
  }, [storeId, accountId, scope, version]);
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === null || event.key.startsWith('melorin:loyalty-redemption:')) refresh();
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, [refresh]);
  const current = snapshot?.scope === scope ? snapshot : null;
  return {
    attempts: current?.attempts || [],
    ready: !!current && !current.error,
    error: current?.error || false,
    refresh,
  };
}
