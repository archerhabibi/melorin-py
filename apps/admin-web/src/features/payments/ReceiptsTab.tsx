// «رسیدها» — everything about how card-to-card receipts are treated: the fast-review queue with provisional approval and
// the duplicate-picture policy (ReceiptReviewPanel), then how a receipt image is read (ReceiptOcrSettings).
import { Landmark } from 'lucide-react';
import { Empty } from '../../shared/kit.tsx';
import ReceiptReviewPanel from './ReceiptReviewPanel.tsx';
import ReceiptOcrSettings from './ReceiptOcrSettings.tsx';
import type { ReceiptFetcher } from './receiptFile.ts';
import type { CallFn, Json, Toast } from '../../shared/types.ts';

export default function ReceiptsTab({
  api,
  call,
  store,
  receipt,
  toast,
  onChanged,
}: {
  api?: Json;
  call: CallFn;
  store: string | false | null;
  receipt: ReceiptFetcher;
  toast: Toast;
  onChanged?: () => void;
}) {
  if (store === null) return <div className="card skel h-48" />;
  return (
    <div className="space-y-5">
      {store ? (
        <ReceiptReviewPanel
          call={call}
          toast={toast}
          base={`/api/v1/admin/stores/${store}`}
          receipt={receipt}
          onChanged={onChanged}
        />
      ) : (
        <Empty
          Icon={Landmark}
          title="فروشگاه اصلی پیدا نشد"
          text="بازبینی رسیدها به فروشگاه اصلی وابسته است. بعد از ساخت فروشگاه اصلی اینجا فعال می‌شود."
        />
      )}
      <ReceiptOcrSettings api={api} toast={toast} />
    </div>
  );
}
