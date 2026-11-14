// Headless logic of the broadcast composer (پیام همگانی). Admin-web (picks an audience) and store-web (own customers only) render their own
// markup; the draft state, the confirm step, the POST and the error handling are written once. Core decides who is reached.
import { useCallback, useEffect, useState } from 'react';
import { errText } from './format.js';

export const TITLE_MAX = 120;
export const BODY_MAX = 3500;

/** Keep polling `reload` every 8 s while any message still has queued deliveries. */
export function usePollWhileQueued(items, reload) {
  const queued = (items || []).some((b) => b.queued > 0);
  useEffect(() => {
    if (!queued) return undefined;
    const t = setInterval(reload, 8000);
    return () => clearInterval(t);
  }, [queued, reload]);
  return queued;
}

/**
 * @param {{ post: (payload: {title: string, body: string}) => Promise<Response>,
 *           confirm: (title: string) => Promise<boolean> | boolean,
 *           onSent: (result: any) => Promise<void> | void }} cfg
 */
export function useBroadcastComposer({ post, confirm, onSent }) {
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const filled = Boolean(title.trim() && body.trim());
  const send = useCallback(async () => {
    setError('');
    if (!(await confirm(title.trim()))) return;
    setBusy(true);
    try {
      const r = await post({ title: title.trim(), body: body.trim() });
      if (!r.ok) setError(await errText(r, 'ارسال ناموفق بود'));
      else {
        const d = await r.json();
        setTitle('');
        setBody('');
        await onSent(d);
      }
    } catch {
      setError('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy(false);
    }
  }, [title, body, post, confirm, onSent]);
  return { title, setTitle, body, setBody, busy, error, filled, send };
}
