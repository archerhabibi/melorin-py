// IndexedDB read/write transactions serialize localStorage updates across tabs.
export async function withAttemptLock<T>(operation: () => T): Promise<T> {
  const db = await new Promise<IDBDatabase>((resolve, reject) => {
    let blocked = false;
    const request = indexedDB.open('melorin-attempt-lock', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('locks');
    request.onerror = () => reject(request.error || new Error('storage unavailable'));
    request.onblocked = () => {
      blocked = true;
      reject(new Error('storage blocked'));
    };
    request.onsuccess = () => {
      if (blocked) request.result.close();
      else resolve(request.result);
    };
  });
  try {
    return await new Promise<T>((resolve, reject) => {
      const tx = db.transaction('locks', 'readwrite');
      let value: T;
      let failure: unknown;
      const gate = tx.objectStore('locks').get('gate');
      gate.onsuccess = () => {
        try {
          value = operation();
        } catch (error) {
          failure = error;
          tx.abort();
        }
      };
      tx.oncomplete = () => resolve(value);
      tx.onabort = () => reject(failure || tx.error || new Error('storage unavailable'));
    });
  } finally {
    db.close();
  }
}
