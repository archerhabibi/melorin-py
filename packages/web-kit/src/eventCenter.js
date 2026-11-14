// Headless logic of the Telegram Event Center screen. Admin-web (main store) and store-web (reseller store) render their
// own markup; the state machine and the Core calls are written once here. Core validates and sends, the screen only edits.
import { useCallback, useEffect, useState } from 'react';
import { digits, errText } from './format.js';

const JSON_HEADERS = { 'Content-Type': 'application/json' };

/**
 * @param {{ call: (path: string, init?: RequestInit) => Promise<Response>, url: string,
 *           notify: (msg: string) => void, confirm: (msg: string) => Promise<boolean> | boolean }} cfg
 */
export function useEventCenter({ call, url, notify, confirm }) {
  const [data, setData] = useState(null);
  const [chat, setChat] = useState('');
  const [threads, setThreads] = useState({});
  const [enabled, setEnabled] = useState(true);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [failed, setFailed] = useState(false);
  const [results, setResults] = useState(null);
  const [check, setCheck] = useState(null);
  const [made, setMade] = useState(null);

  const apply = (d) => {
    setData(d);
    setChat(d.chat_id || '');
    setEnabled(d.is_enabled !== false);
    setNote(d.note || '');
    setThreads(Object.fromEntries((d.topics || []).map((t) => [t.key, t.thread_id ? String(t.thread_id) : ''])));
  };
  const load = useCallback(async () => {
    try {
      const r = await call(url);
      if (!r.ok) throw new Error('load');
      apply(await r.json());
      setFailed(false);
    } catch {
      setFailed(true);
      setData((x) => x || { configured: false, bot_ready: true, chat_id: '', is_enabled: true, note: '', topics: [] });
    }
  }, [call, url]);
  useEffect(() => {
    load();
  }, [load]);

  const act = async (name, fn) => {
    setError('');
    setBusy(name);
    try {
      await fn();
    } catch {
      setError('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy('');
    }
  };
  const post = (path) => call(`${url}/${path}`, { method: 'POST', headers: JSON_HEADERS, body: '{}' });

  const save = () =>
    act('save', async () => {
      const topics = Object.fromEntries(Object.entries(threads).map(([k, v]) => [k, digits(v)]));
      const r = await call(url, {
        method: 'PUT',
        headers: JSON_HEADERS,
        body: JSON.stringify({ chat_id: chat.trim(), topics, is_enabled: enabled, note: note.trim() || null }),
      });
      if (!r.ok) return setError(await errText(r, 'ذخیره ناموفق بود'));
      apply(await r.json());
      notify('تنظیمات مرکز رویداد ذخیره شد');
    });

  const test = () =>
    act('test', async () => {
      const r = await post('test');
      if (!r.ok) return setError(await errText(r, 'ارسال تست ناموفق بود'));
      setResults((await r.json()).results || []);
      await load();
    });

  const inspect = () =>
    act('check', async () => {
      const r = await post('check');
      if (!r.ok) return setError(await errText(r, 'بررسی گروه ناموفق بود'));
      setCheck(await r.json());
    });

  const provision = () =>
    act('provision', async () => {
      const r = await post('provision');
      if (!r.ok) return setError(await errText(r, 'ساخت Topicها ناموفق بود'));
      const d = await r.json();
      setMade(d.results || []);
      setCheck(null);
      await load();
      if (d.created || d.recreated) {
        notify(
          [d.created && `${d.created} Topic ساخته شد`, d.recreated && `${d.recreated} Topic حذف‌شده دوباره ساخته شد`]
            .filter(Boolean)
            .join('، '),
        );
      }
    });

  const remove = async () => {
    if (!(await confirm('اتصال گروه حذف شود؟ از این پس هیچ رویدادی به تلگرام ارسال نمی‌شود.'))) return;
    await act('delete', async () => {
      const r = await call(url, { method: 'DELETE' });
      if (!r.ok) return setError(await errText(r, 'حذف ناموفق بود'));
      setResults(null);
      notify('گروه رویدادها حذف شد');
      await load();
    });
  };

  return {
    data, chat, setChat, threads, setThreads, enabled, setEnabled, note, setNote,
    busy, error, failed, results, check, made, save, test, inspect, provision, remove, reload: load,
  };
}
