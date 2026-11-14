// Headless data layer of the loyalty club screen (program, rewards, summary of ONE store). Admin-web (store picker) and store-web
// (the reseller's own store) render their own markup; loading, the revision counter that resets the edit forms, and the write
// helper are written once. The store id is in `url`, never in a body; Core decides every value.
import { useCallback, useEffect, useState } from 'react';
import { errText } from './format.js';

const JSON_HEADERS = { 'Content-Type': 'application/json' };

/**
 * @param {{ call: (path: string, init?: RequestInit) => Promise<Response>, url: string | null,
 *           notify: (msg: string) => void }} cfg  `url` null = nothing selected yet
 */
export function useLoyaltyClub({ call, url, notify }) {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);
  const [rev, setRev] = useState(0);
  const load = useCallback(async () => {
    if (!url) return;
    try {
      const [a, b, c] = await Promise.all([call(`${url}/program`), call(`${url}/rewards`), call(`${url}/summary`)]);
      if (!a.ok || !b.ok || !c.ok) throw new Error('load');
      setData({ prog: await a.json(), rewards: await b.json(), sum: await c.json() });
      setFailed(false);
      setRev((n) => n + 1);
    } catch {
      setFailed(true);
    }
  }, [call, url]);
  useEffect(() => {
    setData(null);
    setFailed(false);
    load();
  }, [load]);

  /** One write (PUT/POST) under the club; toasts the outcome and reloads on success. Resolves true when Core accepted it. */
  const write = useCallback(
    async (path, method, payload, okText, failText) => {
      const r = await call(`${url}${path}`, { method, headers: JSON_HEADERS, body: JSON.stringify(payload) });
      if (r.ok) {
        notify(okText);
        load();
        return true;
      }
      notify(await errText(r, failText));
      return false;
    },
    [call, url, notify, load],
  );
  return { data, failed, rev, load, write };
}

/** Tiers to show: the saved ladder, or a copy of Core's default ladder when the store has none yet. */
export const tiersOf = (prog) => (prog.tiers.length ? prog.tiers : prog.default_tiers.map((t) => ({ ...t })));
