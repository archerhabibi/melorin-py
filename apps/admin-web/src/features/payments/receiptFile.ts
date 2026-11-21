// Receipt images are private binary downloads (GET /api/v1/admin/payments/{payment_id}/receipt). The screens that show
// them share one fetcher type (built from the typed client's `rawGet`) and one way of opening the result.

/** Resolves the unread Response of a receipt download; auth + refresh come from the typed client. */
export type ReceiptFetcher = (paymentId: string) => Promise<Response>;

/** Long enough for the new tab to load the blob, short enough not to keep a receipt in memory for the whole session. */
export const BLOB_TAB_TTL_MS = 60_000;

/** Open a blob in a new tab (noopener) and release its object URL afterwards. */
export function openBlobInTab(blob: Blob, ttlMs = BLOB_TAB_TTL_MS): void {
  const url = URL.createObjectURL(blob);
  window.open(url, '_blank', 'noopener');
  setTimeout(() => URL.revokeObjectURL(url), ttlMs);
}
