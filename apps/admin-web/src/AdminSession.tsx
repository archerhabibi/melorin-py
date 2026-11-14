import { useCallback, useEffect, useState } from 'react';
import { API_BASE, authFetch, getJson } from './api.ts';
import type { AdminMe, Json, Rec } from './types.ts';

export function useCore() {
  const base = API_BASE;
  const [data, setData] = useState<Rec>({
    summary: null,
    attention: null,
    orders: [],
    users: [],
    tickets: [],
    stores: [],
    me: null,
    perms: undefined,
    health: null,
    backups: [],
    pendingApps: 0,
    pendingPanelReq: 0,
    manualTasks: 0,
    loading: true,
    error: '',
  });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    setData((x) => ({ ...x, loading: true }));
    (async () => {
      try {
        // A role may not read every list (a support admin has no reports, a finance admin no panels): each call fails on its own
        // and only a total failure means "Core is unreachable".
        const soft = async (p: string, fallback: unknown) => {
          try {
            return { ok: true, value: await getJson<unknown>(base, p) };
          } catch {
            return { ok: false, value: fallback };
          }
        };
        const raw = await Promise.all([
          soft('/api/v1/admin/reports/summary', null),
          soft('/api/v1/admin/orders', []),
          soft('/api/v1/admin/health', null),
          soft('/api/v1/admin/operations/backups', []),
          soft('/api/v1/admin/users', []),
          soft('/api/v1/admin/tickets', []),
          soft('/api/v1/admin/stores', []),
          soft('/api/v1/admin/dashboard', null),
        ]);
        if (raw.every((x) => !x.ok)) throw new Error('unreachable');
        const [summary, orders, health, backups, users, tickets, stores, dashboard] = raw.map((x) => x.value) as Rec[];
        const attention = (dashboard as Rec | null)?.attention ?? null;
        const me = await getJson<AdminMe>(base, '/api/v1/admin/me').catch(() => null);
        const pendingApps = await getJson(base, '/api/v1/admin/reseller-applications?status=pending')
          .then((x) => x.length)
          .catch(() => 0);
        const pendingPanelReq = await getJson(base, '/api/v1/admin/panel-admin-requests?status=pending')
          .then((x) => x.length)
          .catch(() => 0);
        const manualTasks = await getJson(base, '/api/v1/admin/manual-tasks?status=open')
          .then((x) => x.open || 0)
          .catch(() => 0);
        if (live)
          setData({
            summary,
            attention,
            orders,
            health,
            backups,
            users,
            tickets,
            stores,
            me,
            perms: me ? me.permissions : [],
            pendingApps,
            pendingPanelReq,
            manualTasks,
            loading: false,
            error: '',
          });
      } catch (e: Json) {
        if (live)
          setData((x) => ({
            ...x,
            loading: false,
            error: 'اتصال به Core API برقرار نشد. وارد شوید یا آدرس API را بررسی کنید.',
          }));
      }
    })();
    return () => {
      live = false;
    };
  }, [base, tick]);
  const refresh = useCallback(() => setTick((x) => x + 1), []);
  return { ...(data as Rec), base, refresh, tick } as Rec;
}

export async function downloadOrders(base: string) {
  const r = await authFetch(base, '/api/v1/admin/reports/orders.csv');
  if (!r.ok) throw Error(`export ${r.status}`);
  const blob = await r.blob(),
    url = URL.createObjectURL(blob),
    a = document.createElement('a');
  a.href = url;
  a.download = 'melorin-orders.csv';
  a.click();
  URL.revokeObjectURL(url);
}
export async function refundPayment(base: string, paymentId: Json, reason: Json) {
  const r = await authFetch(base, `/api/v1/admin/payments/${paymentId}/refund`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  });
  if (!r.ok) throw Error(`refund ${r.status}`);
  return r.json();
}
