import { useEffect, useState } from 'react';
import type { Json, Toast } from './types.ts';
import { money, box, inp, ghost, useList, Table, Form } from './adminExtraKit.tsx';

export default function Coupons({ api, toast }: { api?: Json; toast: Toast }) {
  const stores = useList(api, '/api/v1/admin/stores', toast).rows;
  const [storeId, setStoreId] = useState<Json>(null); // null = not chosen yet, '' = every store (also multi-store codes)
  useEffect(() => {
    if (storeId === null && stores.length) setStoreId((stores.find((s) => s.kind === 'main') || stores[0]).id);
  }, [stores, storeId]);
  // a discount code belongs to ONE store: the form below always creates for the store picked here
  const { rows, call, reload } = useList(api, `/api/v1/admin/coupons${storeId ? `?store_id=${storeId}` : ''}`, toast);
  const store = stores.find((s) => s.id === storeId);
  const create = async (v: Json, done: Json) => {
    if (!storeId) return toast('ابتدا یک فروشگاه مشخص را انتخاب کنید');
    const r = await call('/api/v1/admin/coupons', {
      method: 'POST',
      body: JSON.stringify({
        code: v.code,
        percent_bp: Math.round((+v.pct || 0) * 100),
        fixed: +v.fixed || 0,
        max_redemptions: v.max ? +v.max : null,
        scope: 'store',
        store_id: storeId,
      }),
    });
    if (r.ok) {
      toast('کوپن ساخته شد');
      done();
      reload();
    } else toast('ساخت کوپن ناموفق بود');
  };
  const toggle = async (c: Json) => {
    const r = await call(`/api/v1/admin/coupons/${c.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ status: c.status === 'active' ? 'disabled' : 'active' }),
    });
    r.ok ? reload() : toast('تغییر ناموفق بود');
  };
  return (
    <>
      <section className={`${box} rise p-4`}>
        <label className="block text-xs font-bold text-[var(--mu)]">
          فروشگاه (کد تخفیف فقط در همین فروشگاه کار می‌کند)
          <select
            className={`${inp} mt-1.5`}
            aria-label="فروشگاه"
            value={storeId ?? ''}
            onChange={(e) => setStoreId(e.target.value)}
          >
            <option value="">همه (شامل کدهای چندفروشگاهی)</option>
            {stores.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} {s.kind === 'main' ? '(اصلی)' : '(نمایندگی)'} · {s.currency}
              </option>
            ))}
          </select>
        </label>
      </section>
      <Form
        label={`افزودن کوپن${store ? ` برای «${store.name}»` : ''}`}
        onSubmit={create}
        fields={[
          ['code', 'کد'],
          ['pct', 'درصد تخفیف', 'number'],
          ['fixed', 'تخفیف ثابت', 'number'],
          ['max', 'سقف استفاده', 'number'],
        ]}
      />
      <Table
        title="کوپن‌ها"
        cols={['کد', 'درصد', 'ثابت', 'استفاده', 'وضعیت', '']}
        rows={rows.map((c) => [
          c.code,
          c.percent_bp != null ? `${c.percent_bp / 100}%` : '-',
          money(c.fixed),
          `${c.redeemed ?? c.redemptions ?? 0}/${c.max_redemptions ?? '∞'}`,
          c.status,
          <button key="toggle" className={ghost} onClick={() => toggle(c)}>
            {c.status === 'active' ? 'غیرفعال' : 'فعال'}
          </button>,
        ])}
      />
    </>
  );
}
