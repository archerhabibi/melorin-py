// Per-store availability of one product (GET/POST /admin/products/{id}/availability?store_id=): sold in this store at all,
// and listed in its storefront. The reseller's own price is not touched here (the reseller sets it).
import { useEffect, useState } from 'react';
import { Toggle, errText } from './kit.tsx';
import type { CallFn } from './types.ts';
import { errMessage } from './adminHubTypes.ts';
import type { StoreRow } from './adminHubTypes.ts';

export default function ProductAvailability({
  call,
  productId,
  stores,
  toast,
  writable = true,
}: {
  call: CallFn;
  productId: string;
  stores: StoreRow[];
  toast: (m: string) => void;
  writable?: boolean;
}) {
  const [storeId, setStoreId] = useState('');
  const [state, setState] = useState<{ enabled: boolean; listed: boolean } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setState(null);
    if (!storeId) return;
    (async () => {
      try {
        const r = await call(`/api/v1/admin/products/${productId}/availability?store_id=${storeId}`);
        if (!r.ok) throw new Error(await errText(r, String(r.status)));
        setState(await r.json());
      } catch {
        toast('دریافت وضعیت فروش ناموفق بود');
      }
    })();
  }, [call, productId, storeId, toast]);

  const save = async (next: { enabled: boolean; listed: boolean }) => {
    setBusy(true);
    try {
      const r = await call(`/api/v1/admin/products/${productId}/availability`, {
        method: 'POST',
        body: JSON.stringify({ store_id: storeId, ...next }),
      });
      if (!r.ok) throw new Error(await errText(r, String(r.status)));
      setState(next);
      toast('ذخیره شد');
    } catch (e) {
      toast(`ناموفق: ${errMessage(e)}`);
    }
    setBusy(false);
  };

  return (
    <section className="space-y-2 border-t border-[var(--bd)] pt-3">
      <h3 className="font-extrabold">فروش در هر فروشگاه</h3>
      <select className="inp w-full" value={storeId} onChange={(e) => setStoreId(e.target.value)} aria-label="فروشگاه">
        <option value="">یک فروشگاه انتخاب کنید</option>
        {stores.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </select>
      {state && (
        <div className="space-y-2" aria-busy={busy}>
          <Toggle
            checked={!!state.enabled}
            onChange={(v: boolean) => writable && !busy && save({ enabled: v, listed: state.listed })}
            label="قابل فروش در این فروشگاه"
          />
          <Toggle
            checked={!!state.listed}
            onChange={(v: boolean) => writable && !busy && save({ enabled: state.enabled, listed: v })}
            label="نمایش در ویترین"
          />
        </div>
      )}
    </section>
  );
}
