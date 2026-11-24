import { listStoredAttempts, updateStoredAttempt } from './attemptLock.ts';

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
  const start = prefix(storeId, accountId);
  const pending: PendingReward[] = [];
  for (const [storageKey, raw] of await listStoredAttempts(start)) {
    const rewardId = decodeURIComponent(storageKey.slice(start.length));
    const saved = readAttempt(raw);
    if (!rewardId || !saved) throw new Error('invalid stored redemption');
    pending.push({ rewardId, ...saved });
  }
  return pending;
}

export async function reserveReward(
  storeId: string,
  accountId: string,
  rewardId: string,
  name: string,
  expectedKey?: string,
): Promise<string | null> {
  const storageKey = prefix(storeId, accountId) + encodeURIComponent(rewardId);
  return updateStoredAttempt(storageKey, (raw) => {
    const saved = readAttempt(raw);
    if (expectedKey && saved?.key !== expectedKey) return { result: null };
    const attempt = saved || { name, key: crypto.randomUUID() };
    return { value: JSON.stringify(attempt), result: attempt.key };
  });
}

export async function completeReward(storeId: string, accountId: string, rewardId: string, expectedKey: string) {
  const storageKey = prefix(storeId, accountId) + encodeURIComponent(rewardId);
  return updateStoredAttempt(storageKey, (raw) => {
    if (readAttempt(raw)?.key !== expectedKey) return { result: undefined };
    return { value: null, result: undefined };
  });
}
