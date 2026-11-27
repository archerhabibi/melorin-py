// «پرداخت‌ها» — the payments hub. The old screen stacked KPIs, the review queue, the list, bank-SMS auto verification,
// fast receipt review, the duplicate-picture policy, gateway settings and OCR into one endless page. Now it is one screen
// with four tabs, split by what the admin is doing (docs/09):
//   transactions «تراکنش‌ها»   what came in, what waits for a decision, refunds                (TransactionsTab)
//   receipts     «رسیدها»       provisional approval, duplicate pictures, how receipts are read  (ReceiptsTab)
//   sms          «پیامک بانک»   automatic card-to-card verification by the bank's SMS            (BankSmsPanel)
//   gateways     «درگاه‌ها»     card and Zarinpal details of the main store                      (GatewaysTab)
// Deep links: #/payments (transactions), #/payments?tab=receipts|sms|gateways. The tabs that need attention carry a badge,
// so an urgent item is visible from any tab.
import { lazy, Suspense, useCallback, useMemo, useState } from 'react';
import { useCall } from '../../api/api.ts';
import { Segmented, num } from '../../shared/kit.tsx';
import type { ReceiptFetcher } from './receiptFile.ts';
import { reviewable } from './paymentsShared.tsx';
import { useMainStore, usePayments, useProvisionalCount } from './usePaymentsData.ts';
import type { Json, Toast } from '../../shared/types.ts';

const TransactionsTab = lazy(() => import('./TransactionsTab.tsx'));
const ReceiptsTab = lazy(() => import('./ReceiptsTab.tsx'));
const BankSmsPanel = lazy(() => import('./BankSmsPanel.tsx'));
const GatewaysTab = lazy(() => import('./GatewaysTab.tsx'));

const TABS = ['transactions', 'receipts', 'sms', 'gateways'] as const;
type Tab = (typeof TABS)[number];
const HINT: Record<Tab, string> = {
  transactions: 'رسیدهای منتظر تصمیم، پیگیری تراکنش‌ها و استرداد',
  receipts: 'تأیید موقت، سیاست تصویر تکراری و نحوه‌ی خواندن رسید',
  sms: 'تأیید خودکار کارت‌به‌کارت با پیامک واریز بانک',
  gateways: 'اطلاعات کارت و درگاه زرین‌پال فروشگاه اصلی',
};
const tabFromHash = (): Tab => {
  const q = typeof window === 'undefined' ? '' : window.location.hash.split('?')[1] || '';
  const t = new URLSearchParams(q).get('tab') as Tab | null;
  return t && TABS.includes(t) ? t : 'transactions';
};

export default function PaymentsView({ api, toast }: { api?: Json; toast: Toast }) {
  const call = useCall(api);
  const store = useMainStore();
  const { client, rows, failed, reload } = usePayments(api?.base);
  const { count: provisional, refresh: refreshProvisional } = useProvisionalCount(call, store);
  const [tab, setTab] = useState<Tab>(tabFromHash);

  // the same typed fetcher serves the detail drawer and the receipts tab
  const receipt = useCallback<ReceiptFetcher>(
    (paymentId) =>
      client.rawGet('/api/v1/admin/payments/{payment_id}/receipt', {
        params: { path: { payment_id: paymentId } },
      }),
    [client],
  );
  const waiting = useMemo(() => (rows || []).filter(reviewable).length, [rows]);

  const pick = (v: Tab) => {
    setTab(v);
    // replaceState: switching tabs adds no history entry
    window.history.replaceState(
      null,
      '',
      `${window.location.pathname}${window.location.search}#/payments${v === 'transactions' ? '' : `?tab=${v}`}`,
    );
  };
  const badge = (n: number) => n > 0 && <b className="num mr-1.5">{num(n)}</b>;

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-extrabold">پرداخت‌ها</h2>
        <p className="mt-1 text-xs text-[var(--mu)]">{HINT[tab]}</p>
      </div>
      <Segmented
        label="بخش پرداخت‌ها"
        value={tab}
        onChange={pick}
        options={[
          ['transactions', <>تراکنش‌ها {badge(waiting)}</>],
          ['receipts', <>رسیدها {badge(provisional)}</>],
          ['sms', 'پیامک بانک'],
          ['gateways', 'درگاه‌ها'],
        ]}
      />
      <Suspense fallback={<div className="skel h-44" />}>
        {tab === 'transactions' && (
          <TransactionsTab
            client={client}
            rows={rows}
            failed={failed}
            reload={reload}
            receipt={receipt}
            toast={toast}
          />
        )}
        {tab === 'receipts' && (
          <ReceiptsTab
            api={api}
            call={call}
            store={store}
            receipt={receipt}
            toast={toast}
            onChanged={() => {
              reload();
              refreshProvisional();
            }}
          />
        )}
        {tab === 'sms' && <BankSmsPanel toast={toast} payments={rows} />}
        {tab === 'gateways' && <GatewaysTab client={client} toast={toast} />}
      </Suspense>
    </div>
  );
}
