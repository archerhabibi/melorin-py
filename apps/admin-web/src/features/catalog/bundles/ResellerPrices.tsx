import { useEffect, useState } from 'react';
import { Section, num } from '../../../shared/kit.tsx';
import type { CallFn, Json, Rec } from '../../../shared/types.ts';

/** READ-ONLY: what each reseller store charges in this bundle. The admin cannot change these; resellers set them. */
export function ResellerPrices({ group, stores, call }: { group?: Json; stores?: Json; call: CallFn }) {
  const [sid, setSid] = useState(stores[0]?.id || ''),
    [rows, setRows] = useState<Json>(null);
  useEffect(() => {
    if (!sid) return;
    setRows(null);
    call(`/api/v1/admin/stores/${sid}/reseller-prices`)
      .then((r: Json) => (r.ok ? r.json() : []))
      .then(setRows)
      .catch(() => setRows([]));
  }, [sid]); // eslint-disable-line react-hooks/exhaustive-deps
  const list = (rows || [])
    .map((r: Json) => ({ r, b: (r.bundles || []).find((x: Json) => x.bundle_id === group.id) }))
    .filter((x: Json) => x.b);
  const ST: Rec = { ok: ['ok', 'قابل فروش'], unset: ['mu', 'قیمت ندارد'], below_cost: ['bd', 'زیر قیمت نماینده'] };
  return (
    <Section
      title="قیمت فروش نمایندگان (فقط نمایش)"
      hint="این قیمت‌ها را خود نماینده تعیین می‌کند و ادمین نمی‌تواند تغییرشان دهد."
    >
      <select aria-label="نماینده" className="inp" value={sid} onChange={(e) => setSid(e.target.value)}>
        {stores.map((s: Json) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </select>
      {rows === null ? (
        <div className="skel h-12 rounded-xl" />
      ) : !list.length ? (
        <p className="text-xs text-[var(--mu)]">پکیجی برای نمایش نیست.</p>
      ) : (
        <div className="overflow-auto">
          <table className="tbl2 min-w-[420px]">
            <thead>
              <tr>
                {['پکیج', 'قیمت نماینده', 'قیمت فروش او', 'وضعیت'].map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {list.map(({ r, b }: Json) => {
                const [t, l] = ST[b.state] || ST.unset;
                return (
                  <tr key={r.product_id}>
                    <td className="font-bold">{r.name}</td>
                    <td className="num">{num(b.cost)}</td>
                    <td className="num">{b.effective_price ? num(b.effective_price) : '—'}</td>
                    <td>
                      <span className={`badge b-${t}`}>{l}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}
