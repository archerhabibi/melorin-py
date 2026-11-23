const databaseName = 'melorin-attempt-lock';
const storeName = 'attempts';
const migrationKey = '__melorin_attempts_migrated__';
const storageGuard = 'melorin:attempt-storage-initialized';
const changeEvent = 'melorin:attempt-storage-changed';
const changeSignal = 'melorin:attempt-storage-signal';
const channelName = 'melorin-attempt-storage';
const legacyPrefixes = ['melorin:order-attempt:', 'melorin:wallet-topup:'];

type Decision<T> = { result: T; value?: string | null };

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    let blocked = false;
    // Version 2 prevents older order flows, which open version 1, from writing
    // localStorage-only attempts after migration.
    const request = indexedDB.open(databaseName, 2);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(storeName)) request.result.createObjectStore(storeName);
    };
    request.onerror = () => reject(request.error || new Error('storage unavailable'));
    request.onblocked = () => {
      blocked = true;
      reject(new Error('storage blocked'));
    };
    request.onsuccess = () => {
      if (blocked) request.result.close();
      else {
        request.result.onversionchange = () => request.result.close();
        resolve(request.result);
      }
    };
  });
}

async function withStore<T>(
  operation: (store: IDBObjectStore, finish: (value: T) => void, fail: (error: unknown) => void) => void,
): Promise<T> {
  const db = await openDatabase();
  try {
    return await new Promise<T>((resolve, reject) => {
      const tx = db.transaction(storeName, 'readwrite');
      const store = tx.objectStore(storeName);
      let value: T;
      let failure: unknown;
      const fail = (error: unknown) => {
        failure = error;
        try {
          tx.abort();
        } catch {
          reject(error);
        }
      };
      tx.oncomplete = () => resolve(value);
      tx.onabort = () => reject(failure || tx.error || new Error('storage unavailable'));

      const migration = store.get(migrationKey);
      migration.onsuccess = () => {
        try {
          if (migration.result === undefined) {
            // A surviving guard means IndexedDB was lost after initialization.
            // Never silently replace potentially unresolved payment keys.
            if (localStorage.getItem(storageGuard) !== null) throw new Error('attempt storage lost');
            for (let i = 0; i < localStorage.length; i++) {
              const key = localStorage.key(i);
              if (!key || !legacyPrefixes.some((prefix) => key.startsWith(prefix))) continue;
              const saved = localStorage.getItem(key);
              if (saved === null) throw new Error('legacy attempt unavailable');
              store.put(saved, key);
            }
            // Write the guard before commit: if the transaction fails, future
            // requests fail closed instead of assuming no attempt existed.
            localStorage.setItem(storageGuard, '1');
            store.put('1', migrationKey);
          } else if (migration.result !== '1') {
            throw new Error('invalid attempt storage');
          }
          operation(
            store,
            (result) => {
              value = result;
            },
            fail,
          );
        } catch (error) {
          fail(error);
        }
      };
    });
  } finally {
    db.close();
  }
}

function notifyChange(key: string) {
  window.dispatchEvent(new CustomEvent(changeEvent, { detail: key }));
  try {
    if (typeof BroadcastChannel !== 'undefined') {
      const channel = new BroadcastChannel(channelName);
      channel.postMessage(key);
      channel.close();
    } else {
      localStorage.setItem(changeSignal, crypto.randomUUID());
    }
  } catch {
    // Notifications are best effort; reads and writes still use IndexedDB.
  }
}

/** Atomically read and update an attempt, committing before its key is used. */
export async function updateStoredAttempt<T>(key: string, decide: (current: string | null) => Decision<T>): Promise<T> {
  let changed = false;
  const result = await withStore<T>((store, finish, fail) => {
    const request = store.get(key);
    request.onsuccess = () => {
      try {
        const saved: unknown = request.result;
        if (saved !== undefined && typeof saved !== 'string') throw new Error('invalid stored attempt');
        const current = saved === undefined ? null : saved;
        const next = decide(current);
        if (next.value !== undefined && next.value !== current) {
          if (next.value === null) store.delete(key);
          else store.put(next.value, key);
          changed = true;
        }
        finish(next.result);
      } catch (error) {
        fail(error);
      }
    };
  });
  if (changed) notifyChange(key);
  return result;
}

/** Read all attempts in a scope from the same authoritative store. */
export async function listStoredAttempts(prefix: string): Promise<Array<[string, string]>> {
  return withStore((store, finish, fail) => {
    const values: Array<[string, string]> = [];
    const request = store.openCursor(IDBKeyRange.bound(prefix, prefix + '￿'));
    request.onsuccess = () => {
      const cursor = request.result;
      if (!cursor) {
        finish(values);
      } else if (typeof cursor.key !== 'string' || typeof cursor.value !== 'string') {
        fail(new Error('invalid stored attempt'));
      } else {
        values.push([cursor.key, cursor.value]);
        cursor.continue();
      }
    };
  });
}

export function subscribeToAttemptChanges(listener: (key: string | null) => void): () => void {
  const onLocal = (event: Event) => listener((event as CustomEvent<string>).detail);
  const onStorage = (event: StorageEvent) => {
    if (
      event.key === null ||
      event.key === changeSignal ||
      legacyPrefixes.some((prefix) => event.key?.startsWith(prefix))
    )
      listener(null);
  };
  const onFocus = () => listener(null);
  window.addEventListener(changeEvent, onLocal);
  window.addEventListener('storage', onStorage);
  window.addEventListener('focus', onFocus);
  let channel: BroadcastChannel | null = null;
  try {
    if (typeof BroadcastChannel !== 'undefined') {
      channel = new BroadcastChannel(channelName);
      channel.onmessage = (event: MessageEvent<unknown>) =>
        listener(typeof event.data === 'string' ? event.data : null);
    }
  } catch {
    // Focus and storage events provide a fallback when channels are unavailable.
  }
  return () => {
    channel?.close();
    window.removeEventListener(changeEvent, onLocal);
    window.removeEventListener('storage', onStorage);
    window.removeEventListener('focus', onFocus);
  };
}
