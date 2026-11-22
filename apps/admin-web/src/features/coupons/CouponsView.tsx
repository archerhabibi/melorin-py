import { useRef, useState } from 'react';
import type { Toast } from '../../shared/types.ts';
import { ErrorBar, errText, num } from '../../shared/kit.tsx';
import { dt } from '../../shared/ui.tsx';
import { money, box, inp, ghost, Table, Form } from '../../app/adminExtraKit.tsx';
import { COUPON_FIELDS, buildCouponBody, nextStatus } from './couponForm.ts';
import type { CouponFormValues, CouponRow } from './couponForm.ts';
import { useCoupons } from './useCoupons.ts';

export default function Coupons({ api, toast }: { api?: { base?: string }; toast: Toast }) {
  const { client, stores, storeId, setStoreId, rows, failed, reload } = useCoupons(api?.base, toast);
  const store = stores.find((s) => s.id === storeId);
  const [busyId, setBusyId] = useState<string | null>(null);
  const creating = useRef(false);

  // a discount code belongs to ONE store: the form below always creates for the store picked here
  const create = async (v: CouponFormValues, done: () => void) => {
    if (creating.current) return;
    if (!storeId) return toast('ابتدا یک فروشگاه مشخص را انتخاب کنید');
    const built = buildCouponBody(v, storeId);
    if ('error' in built) return toast(built.error);
    creating.current = true;
    try {
      const { response } = await client.post('/api/v1/admin/coupons', { body: built.body });
      if (response.ok) {
        toast('کوپن ساخته شد');
        done();
        reload();
      } else toast(await errText(response, 'ساخت کوپن ناموفق بود')); // Core's own reason (duplicate code, bad value ...)
    } catch {
      toast('ارتباط با سرور برقرار نشد');
    } finally {
      creating.current = false;
    }
  };

  const toggle = async (c: CouponRow) => {
    if (busyId) return;
    setBusyId(c.id);
    try {
      const { response } = await client.patch('/api/v1/admin/coupons/{coupon_id}', {
        params: { path: { coupon_id: c.id } },
        body: { status: nextStatus(c.status) },
      });
      if (response.ok) reload();
      else toast(await errText(response, 'تغییر ناموفق بود'));
    } catch {
      toast('ارتباط با سرور برقرار نشد');
    } finally {
      setBusyId(null);
    }
  };

  const owner = (c: CouponRow) =>
    c.scope === 'domain' ? 'چندفروشگاهی' : (stores.find((s) => s.id === c.store_id)?.name ?? '-');

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
      <Form label={`افزودن کوپن${store ? ` برای «${store.name}»` : ''}`} onSubmit={create} fields={COUPON_FIELDS} />
      {failed && <ErrorBar onRetry={reload}>دریافت کوپن‌ها ناموفق بود.</ErrorBar>}
      <Table
        title="کوپن‌ها"
        cols={['کد', 'فروشگاه', 'درصد', 'ثابت', 'استفاده', 'پایان', 'وضعیت', '']}
        rows={(rows ?? []).map((c) => [
          c.code,
          owner(c),
          c.percent_bp ? `${num(c.percent_bp / 100)}٪` : '-',
          c.fixed ? `${money(c.fixed)}${c.currency ? ` ${c.currency}` : ''}` : '-',
          `${num(c.redemptions)}/${c.max_redemptions == null ? '∞' : num(c.max_redemptions)}`,
          c.ends_at ? dt(c.ends_at) : '-',
          c.status,
          <button key="toggle" className={ghost} disabled={busyId === c.id} onClick={() => toggle(c)}>
            {c.status === 'active' ? 'غیرفعال' : 'فعال'}
          </button>,
        ])}
        extra={
          rows === null && !failed ? <span className="text-xs text-[var(--mu)]">در حال بارگذاری…</span> : undefined
        }
      />
    </>
  );
}
