// Warning card on the bundles screen: products no bundle sells (GET /admin/bundle-products/unassigned).
// Customers cannot buy them until an admin puts them in a bundle. Hidden when there are none.
import { useEffect, useState } from 'react';
import type { CallFn } from './types.ts';
import { asList } from './adminHubTypes.ts';

interface Unassigned {
  product_id: string;
  name: string;
  is_active: boolean;
}

export default function UnassignedProducts({ call }: { call: CallFn }) {
  const [rows, setRows] = useState<Unassigned[]>([]);
  useEffect(() => {
    (async () => {
      try {
        const r = await call('/api/v1/admin/bundle-products/unassigned');
        if (r.ok) setRows(asList<Unassigned>(await r.json()));
      } catch {
        setRows([]);
      }
    })();
  }, [call]);
  if (rows.length === 0) return null;
  return (
    <div className="card space-y-1 p-3" role="status">
      <div className="font-extrabold">محصولی بدون بسته فروش ({rows.length.toLocaleString('fa-IR')})</div>
      <p className="text-sm text-[var(--mu)]">مشتری این محصول‌ها را نمی‌تواند بخرد تا در یک بسته فروش قرار بگیرند:</p>
      <div className="flex flex-wrap gap-1">
        {rows.map((p) => (
          <span key={p.product_id} className="pill">
            {p.name}
            {!p.is_active && ' (غیرفعال)'}
          </span>
        ))}
      </div>
    </div>
  );
}
