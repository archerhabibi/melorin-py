import { withAttemptLock } from './attemptLock.ts';

export type PendingReward = { rewardId: string; name: string; key: string };
type StoredAttempt = { name: string; key: string };

function prefix(storeId: string, accountId: string) {
  return 'melorin:loyalty-redemption:' + encodeURIComponent(storeId) + ':' + encodeURIComponent(accountId) + ':';
}

function readAttempt(raw: string | null): StoredAttempt | null {
  if (raw === null) return null;
  const attempt: unknown = JSON.parse(raw);
  if (
    !attempt ||
    typeof attempt !== 'object' ||
    !('key' in attempt) ||
    typeof attempt.key !== 'string' ||
    attempt.key.length < 8 ||
    attempt.key.length > 100 ||
    !('name' in attempt) ||
    typeof attempt.name !== 'string' ||
    !attempt.name
  ) {
    throw new Error('invalid stored redemption');
  }
  return { key: attempt.key, name: attempt.name };
}

export async function listPendingRewards(storeId: string, accountId: string): Promise<PendingReward[]> {
  return withAttemptLock(() => {
    const start = prefix(storeId, accountId);
    const pending: PendingReward[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const storageKey = localStorage.key(i);
      if (!storageKey?.startsWith(start)) continue;
      const rewardId = decodeURIComponent(storageKey.slice(start.length));
      const saved = readAttempt(localStorage.getItem(storageKey));
      if (!rewardId || !saved) throw new Error('invalid stored redemption');
      pending.push({ rewardId, ...saved });
    }
    return pending;
  });
}

export async function reserveReward(
  storeId: string,
  accountId: string,
  rewardId: string,
  name: string,
  expectedKey?: string,
): Promise<string | null> {
  return withAttemptLock(() => {
    const storageKey = prefix(storeId, accountId) + encodeURIComponent(rewardId);
    const saved = readAttempt(localStorage.getItem(storageKey));
    if (expectedKey && saved?.key !== expectedKey) return null;
    const attempt = saved || { name, key: crypto.randomUUID() };
    localStorage.setItem(storageKey, JSON.stringify(attempt));
    return attempt.key;
  });
}

export async function completeReward(storeId: string, accountId: string, rewardId: string, expectedKey: string) {
  return withAttemptLock(() => {
    const storageKey = prefix(storeId, accountId) + encodeURIComponent(rewardId);
    if (readAttempt(localStorage.getItem(storageKey))?.key === expectedKey) localStorage.removeItem(storageKey);
  });
}
