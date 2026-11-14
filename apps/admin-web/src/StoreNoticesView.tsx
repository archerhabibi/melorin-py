// «اعلان‌ها» tab of the store hub (PG-06): when a store's customers are warned about low traffic. Moved out of panel operations:
// the setting belongs to one store, not to a panel.
import { useCallback, useEffect, useState } from 'react';
import { authFetch } from './api.ts';
import type { CallFn, Json, Rec, Toast } from './types.ts';

const DEFAULT_LEVELS_TEXT = '80, 90';
function NoticeLevels({ call, toast }: { call: CallFn; toast: Toast }) {
  const [stores, setStores] = useState<Rec[]>([]);
  const [storeId, setStoreId] = useState('');
  const [cfg, setCfg] = useState<Json>(null);
  const [text, setText] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const r = await call('/api/v1/admin/stores');
        if (r.ok) setStores(await r.json());
      } catch {
        toast('دریافت فهرست فروشگاه‌ها ناموفق بود');
      }
    })();
  }, [call, toast]);

  useEffect(() => {
    setCfg(null);
    if (!storeId) return;
    (async () => {
      try {
        const r = await call(`/api/v1/admin/stores/${storeId}/vpn-notices`);
        if (!r.ok) throw new Error(String(r.status));
        const j = await r.json();
        setCfg(j);
        setText(j.traffic_low_levels.join(', '));
      } catch {
        toast('دریافت تنظیمات هشدار ناموفق بود');
      }
    })();
  }, [call, storeId, toast]);

  const parse = () => {
    const parts = text.split(/[,،\s]+/).filter(Boolean);
    const nums = parts.map((x) => (/^\d+$/.test(x) ? Number(x) : NaN));
    return nums.some((n) => !(n >= 1 && n <= 99)) || nums.length > 4 ? null : nums;
  };

  const save = async (reset: Json) => {
    const levels = reset ? null : parse();
    if (!reset && levels === null) {
      toast('حداکثر ۴ عدد صحیح بین ۱ تا ۹۹ وارد کنید (با کاما جدا کنید)');
      return;
    }
    setSaving(true);
    try {
      const r = await call(`/api/v1/admin/stores/${storeId}/vpn-notices`, {
        method: reset ? 'DELETE' : 'PUT',
        body: reset ? undefined : JSON.stringify({ traffic_low_levels: levels }),
      });
      if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.error?.message || String(r.status));
      const j = await r.json();
      setCfg(j);
      setText(j.traffic_low_levels.join(', '));
      toast('ذخیره شد');
    } catch (e: Json) {
      toast(`ناموفق: ${e.message}`);
    }
    setSaving(false);
  };

  return (
    <section className="card space-y-3 p-4">
      <p className="text-sm">
        مشتریان هر فروشگاه وقتی درصد مصرف حجم اکانتشان به این عددها رسید، یک‌بار پیام می‌گیرند. پیش‌فرض:{' '}
        {DEFAULT_LEVELS_TEXT}. لیست خالی یعنی این فروشگاه هشدار حجم نمی‌فرستد.
      </p>
      <select className="inp" value={storeId} onChange={(e) => setStoreId(e.target.value)} aria-label="فروشگاه">
        <option value="">یک فروشگاه انتخاب کنید</option>
        {stores.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </select>
      {cfg && (
        <div className="flex flex-wrap items-center gap-2">
          <input
            className="inp"
            dir="ltr"
            value={text}
            onChange={(e) => setText(e.target.value)}
            aria-label="درصدهای هشدار"
            placeholder={DEFAULT_LEVELS_TEXT}
          />
          <button className="btn" disabled={saving} onClick={() => save(false)}>
            ذخیره
          </button>
          <button className="btn btn-g" disabled={saving || cfg.is_default} onClick={() => save(true)}>
            بازگشت به پیش‌فرض
          </button>
          <span className="text-xs text-[var(--mu)]">
            {cfg.is_default ? 'پیش‌فرض سامانه' : 'تنظیم اختصاصی این فروشگاه'}
          </span>
        </div>
      )}
    </section>
  );
}

export default function StoreNoticesView({ api, toast }: { api?: Json; toast: Toast }) {
  const call = useCallback((p: string, o?: RequestInit) => authFetch(api.base, p, o), [api.base]);
  return <NoticeLevels call={call} toast={toast} />;
}
