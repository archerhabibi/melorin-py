import { expect, it } from 'vitest';
import { listStoredAttempts } from '../src/attemptLock.ts';
import { resetAttemptStorage } from './attemptStorage.js';

it('waits for an earlier storage read before resetting the test database', async () => {
  await resetAttemptStorage();
  const earlierRead = listStoredAttempts('earlier:');
  await resetAttemptStorage();
  await earlierRead;
  await expect(listStoredAttempts('next:')).resolves.toEqual([]);
});
