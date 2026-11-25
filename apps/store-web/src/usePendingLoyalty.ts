import { useCallback, useEffect, useState } from 'react';
import { subscribeToAttemptChanges } from './attemptLock.ts';
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
    return subscribeToAttemptChanges((key) => {
      if (key === null || key.startsWith('melorin:loyalty-redemption:')) refresh();
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
