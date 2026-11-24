import { IDBFactory, IDBKeyRange } from 'fake-indexeddb';
import { listStoredAttempts, updateStoredAttempt } from '../src/attemptLock.ts';

export function resetAttemptStorage() {
  localStorage.clear();
  globalThis.indexedDB = new IDBFactory();
  globalThis.IDBKeyRange = IDBKeyRange;
}

export async function readAttempt(key) {
  return (await listStoredAttempts(key)).find(([storedKey]) => storedKey === key)?.[1] ?? null;
}

export async function writeAttempt(key, value) {
  await updateStoredAttempt(key, () => ({ value, result: undefined }));
}

export function deleteAttemptDatabase() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.deleteDatabase('melorin-attempt-lock');
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error('database still open'));
  });
}
