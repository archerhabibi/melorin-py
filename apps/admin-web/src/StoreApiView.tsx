// «API» tab of the store hub: which reseller stores may create and use API keys for their own site.
// One switch per store: PUT /admin/reseller-stores/{id}/api?enabled=. The keys themselves are managed by the reseller.
import { useCallback, useState } from 'react';
import { authFetch } from './api.ts';
import { canWrite } from './adminAccess.ts';
import { Empty, ErrorBar, Toggle, errText, useRows } from './kit.tsx';
import type { Json, Rec, Toast } from './types.ts';

export default function StoreApiView({ api, toast }: { api?: Json; toast: Toast }) {
  const call = useCallback((p: string, o?: RequestInit) => authFetch(api.base, p, o), [api.base]);
  const { rows, failed, load } = useRows(call, '/api/v1/admin/resellers');
  const [busy, setBusy] = useState('');
  const writable = canWrite(api?.perms, 'نمایندگان');

  const flip = async (s: Rec, enabled: boolean) => {
    setBusy(s.id);
    try {
      const r = await call(`/api/v1/admin/reseller-stores/${s.id}/api?enabled=${enabled}`, { method: 'PUT' });
      if (!r.ok) throw new Error(await errText(r, String(r.status)));
      toast(enabled ? 'دسترسی API فعال شد' : 'دسترسی API غیرفعال شد');
      await load();
    } catch (e: Json) {
      toast(`ناموفق: ${e.message}`);
    }
    setBusy('');
  };

  return (
    <section className="card space-y-3 p-4">
      <p className="text-sm">
        با فعال‌بودن دسترسی API، نماینده می‌تواند برای اتصال سایت خودش کلید API بسازد؛ کلید به همین فروشگاه محدود است.
      </p>
      {failed && <ErrorBar>دریافت فهرست نمایندگان ناموفق بود.</ErrorBar>}
      {rows && rows.length === 0 && <Empty>هنوز نمایندهای ثبت نشده است.</Empty>}
      <div className="divide-y divide-[var(--bd)]">
        {(rows || []).map((s) => (
          <div key={s.id} className="flex items-center justify-between gap-3 py-2">
            <div className="min-w-0">
              <div className="font-extrabold">{s.name}</div>
              <div dir="ltr" className="latin text-xs text-[var(--mu)]">
                {s.slug}
              </div>
            </div>
            <div aria-busy={busy === s.id}>
              <Toggle
                checked={!!s.api_enabled}
                onChange={(v: boolean) => writable && busy !== s.id && flip(s, v)}
                label={`دسترسی API ${s.name}`}
              />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
