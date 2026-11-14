// «ربات‌ها» tab of the store hub: which Telegram bot belongs to which store (GET/POST /admin/bot-store-bindings).
// A binding is how a bot key reaches its store; the reseller bot normally creates its own on onboarding, this is the admin's view and manual path.
import { useCallback, useEffect, useState } from 'react';
import { authFetch } from './api.ts';
import { canWrite } from './adminAccess.ts';
import { Empty, ErrorBar, errText, useRows } from './kit.tsx';
import type { Toast } from './types.ts';
import { asList, errMessage } from './adminHubTypes.ts';
import type { HubApiProp, StoreRow } from './adminHubTypes.ts';

const KIND_LABEL: Record<string, string> = { main: 'ربات اصلی', reseller: 'ربات نماینده' };

export default function StoreBotsView({ api, toast }: { api?: HubApiProp; toast: Toast }) {
  const call = useCallback((p: string, o?: RequestInit) => authFetch(api?.base ?? '', p, o), [api?.base]);
  const { rows, failed, load } = useRows(call, '/api/v1/admin/bot-store-bindings');
  const [stores, setStores] = useState<StoreRow[]>([]);
  const [form, setForm] = useState({ bot_key: '', bot_username: '', store_id: '', bot_kind: 'reseller' });
  const [saving, setSaving] = useState(false);
  const writable = canWrite(api?.perms, 'نمایندگان');

  useEffect(() => {
    (async () => {
      try {
        const r = await call('/api/v1/admin/stores');
        if (r.ok) setStores(asList<StoreRow>(await r.json()));
      } catch {
        toast('دریافت فهرست فروشگاه‌ها ناموفق بود');
      }
    })();
  }, [call, toast]);

  const storeName = (id: string) => stores.find((s) => s.id === id)?.name ?? id;
  const set = (k: string, v: string) => setForm((f) => ({ ...f, [k]: v }));
  const valid = form.bot_key.trim().length >= 8 && !!form.store_id;

  const create = async () => {
    setSaving(true);
    try {
      const body = {
        bot_key: form.bot_key.trim(),
        bot_username: form.bot_username.trim().replace(/^@/, '') || null,
        store_id: form.store_id,
        bot_kind: form.bot_kind,
      };
      const r = await call('/api/v1/admin/bot-store-bindings', { method: 'POST', body: JSON.stringify(body) });
      if (!r.ok) throw new Error(await errText(r, String(r.status)));
      toast('اتصال ربات ثبت شد');
      setForm((f) => ({ ...f, bot_key: '', bot_username: '' }));
      await load();
    } catch (e) {
      toast(`ناموفق: ${errMessage(e)}`);
    }
    setSaving(false);
  };

  return (
    <section className="card space-y-4 p-4">
      <p className="text-sm">
        هر ربات تلگرام با «کلید ربات» به یک فروشگاه وصل می‌شود؛ مشتریان آن ربات فقط محصولات و قیمت‌های همان فروشگاه را
        می‌بینند.
      </p>
      {failed && <ErrorBar onRetry={load}>دریافت اتصال‌های ربات ناموفق بود.</ErrorBar>}
      {rows && rows.length === 0 && <Empty>هنوز رباتی به فروشگاهی وصل نشده است.</Empty>}
      <div className="divide-y divide-[var(--bd)]">
        {(rows || []).map((b) => (
          <div key={b.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <div className="min-w-0">
              <div className="font-extrabold">{storeName(b.store_id)}</div>
              <div dir="ltr" className="latin text-xs text-[var(--mu)]">
                {b.bot_username ? `@${b.bot_username}` : '-'} · {String(b.bot_key).slice(0, 4)}…
              </div>
            </div>
            <div className="text-xs text-[var(--mu)]">
              {KIND_LABEL[b.bot_kind] ?? b.bot_kind} · {b.status}
            </div>
          </div>
        ))}
      </div>
      {writable && (
        <div className="space-y-2 border-t border-[var(--bd)] pt-3">
          <h3 className="font-extrabold">اتصال ربات جدید</h3>
          <div className="grid gap-2 sm:grid-cols-2">
            <input
              className="inp"
              dir="ltr"
              value={form.bot_key}
              onChange={(e) => set('bot_key', e.target.value)}
              aria-label="کلید ربات"
              placeholder="کلید ربات (حداقل ۸ نویسه)"
            />
            <input
              className="inp"
              dir="ltr"
              value={form.bot_username}
              onChange={(e) => set('bot_username', e.target.value)}
              aria-label="نام کاربری ربات"
              placeholder="@username"
            />
            <select
              className="inp"
              value={form.store_id}
              onChange={(e) => set('store_id', e.target.value)}
              aria-label="فروشگاه"
            >
              <option value="">فروشگاه</option>
              {stores.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
            <select
              className="inp"
              value={form.bot_kind}
              onChange={(e) => set('bot_kind', e.target.value)}
              aria-label="نوع ربات"
            >
              <option value="reseller">ربات نماینده</option>
              <option value="main">ربات اصلی</option>
            </select>
          </div>
          <button className="btn" disabled={!valid || saving} onClick={create}>
            ثبت اتصال
          </button>
        </div>
      )}
    </section>
  );
}
