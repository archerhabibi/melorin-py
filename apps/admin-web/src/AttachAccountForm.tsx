// Manual fix for an order stuck in provisioning_failed / manual_review: the account already exists on the panel,
// so attach it to the order (POST /admin/orders/{id}/attach-account). The order completes with that account.
import { useEffect, useState } from 'react';
import { confirmDialog } from './ui.tsx';
import { errText } from './kit.tsx';
import type { CallFn } from './types.ts';
import { asList, errMessage } from './adminHubTypes.ts';

interface ServerRow {
  id: string;
  name: string;
  panel_name: string;
}

export default function AttachAccountForm({
  call,
  orderId,
  toast,
  onDone,
}: {
  call: CallFn;
  orderId: string;
  toast: (m: string) => void;
  onDone: () => void | Promise<void>;
}) {
  const [servers, setServers] = useState<ServerRow[]>([]);
  const [f, setF] = useState({ server_id: '', username: '', panel_ref: '', subscription_url: '', reason: '' });
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: string) => setF((x) => ({ ...x, [k]: v }));

  useEffect(() => {
    (async () => {
      try {
        const r = await call('/api/v1/admin/servers');
        if (r.ok) setServers(asList<ServerRow>(await r.json()));
      } catch {
        toast('دریافت فهرست سرورها ناموفق بود');
      }
    })();
  }, [call, toast]);

  const submit = async () => {
    if (
      !(await confirmDialog('اکانت موجود به این سفارش وصل و سفارش تکمیل می‌شود. ادامه می‌دهید؟', {
        title: 'اتصال اکانت به سفارش',
        ok: 'اتصال',
      }))
    )
      return;
    setBusy(true);
    try {
      const body = {
        server_id: f.server_id,
        username: f.username.trim(),
        panel_ref: f.panel_ref.trim() || null,
        subscription_url: f.subscription_url.trim() || null,
        reason: f.reason.trim() || null,
      };
      const r = await call(`/api/v1/admin/orders/${orderId}/attach-account`, { method: 'POST', body: JSON.stringify(body) });
      if (!r.ok) throw new Error(await errText(r, String(r.status)));
      toast('اکانت به سفارش وصل شد');
      await onDone();
    } catch (e) {
      toast(`ناموفق: ${errMessage(e)}`);
    }
    setBusy(false);
  };

  return (
    <section className="card space-y-2 p-4">
      <h3 className="font-extrabold">اتصال اکانت موجود به سفارش</h3>
      <p className="text-xs text-[var(--mu)]">وقتی اکانت را خودتان روی پنل ساخته‌اید و فقط باید به همین سفارش وصل شود.</p>
      <select className="inp w-full" value={f.server_id} onChange={(e) => set('server_id', e.target.value)} aria-label="سرور">
        <option value="">سرور</option>
        {servers.map((s) => (
          <option key={s.id} value={s.id}>
            {s.panel_name} · {s.name}
          </option>
        ))}
      </select>
      <input className="inp w-full" dir="ltr" value={f.username} onChange={(e) => set('username', e.target.value)} aria-label="نام کاربری اکانت روی پنل" placeholder="username" />
      <input className="inp w-full" dir="ltr" value={f.panel_ref} onChange={(e) => set('panel_ref', e.target.value)} aria-label="شناسه روی پنل" placeholder="شناسه روی پنل (اختیاری)" />
      <input className="inp w-full" dir="ltr" value={f.subscription_url} onChange={(e) => set('subscription_url', e.target.value)} aria-label="لینک اشتراک" placeholder="لینک اشتراک (اختیاری)" />
      <input className="inp w-full" value={f.reason} onChange={(e) => set('reason', e.target.value)} aria-label="دلیل" placeholder="دلیل (برای ممیزی)" />
      <button className="btn" disabled={busy || !f.server_id || !f.username.trim()} onClick={submit}>
        اتصال اکانت
      </button>
    </section>
  );
}
