import { Check, Clock, Minus, Undo2, X } from 'lucide-react';
import { AdminOrderRow, Json, Rec } from '../../shared/types.ts';

export const IN_PROGRESS = ['pending', 'payment_pending', 'paid', 'processing', 'provisioning'];
export const ATTENTION = ['provisioning_failed', 'manual_review', 'refund_pending', 'payment_failed'];
export const CLOSED = ['cancelled', 'refunded'];
// Mirror apps/api/melorin/domain/order_state.py so the UI never offers an action the API would refuse.
export const RETRYABLE = ['provisioning_failed', 'manual_review'];
export const REVIEWABLE = ['provisioning_failed', 'refund_pending'];
export const REFUNDABLE = ['paid', 'provisioning_failed', 'manual_review', 'completed'];
export const CAP = 200; // the endpoint returns the latest 200 orders

// Where an order is on its way: register → pay → build the account → done. `done` = steps fully completed;
// the next step is the active one (tone = how it is going). `as` swaps in a label when the step went off the happy path.
export const STEPS = ['ثبت سفارش', 'پرداخت', 'ساخت اکانت', 'تکمیل'];
export const PROGRESS: Rec = {
  pending: { done: 1, tone: 'wn' },
  payment_pending: { done: 1, tone: 'wn' },
  payment_failed: { done: 1, tone: 'bd', as: 'پرداخت ناموفق' },
  paid: { done: 2, tone: 'in' },
  processing: { done: 2, tone: 'in' },
  provisioning: { done: 2, tone: 'in' },
  manual_review: { done: 2, tone: 'wn', as: 'بررسی دستی' },
  provisioning_failed: { done: 2, tone: 'bd', as: 'ساخت ناموفق' },
  completed: { done: 4, tone: 'ok' },
  refund_pending: { done: 3, tone: 'wn', as: 'در انتظار استرداد' },
  refunded: { done: 3, tone: 'mu', as: 'مسترد شد' },
  cancelled: { done: 1, tone: 'mu', as: 'لغو شد' },
};
export const NodeIcon = ({ tone, status }: { tone?: Json; status?: Json }) =>
  tone === 'bd' ? (
    <X size={14} />
  ) : tone === 'wn' ? (
    <Clock size={14} />
  ) : tone === 'mu' ? (
    status === 'refunded' ? (
      <Undo2 size={13} />
    ) : (
      <Minus size={14} />
    )
  ) : (
    <i className="block h-2 w-2 rounded-full bg-current" />
  );

/** Order lifecycle tracker shown in the drawer. Renders nothing for a status it does not know. */
export function OrderFlow({ status }: { status?: Json }) {
  const p = PROGRESS[status];
  if (!p) return null;
  const cur = p.done < STEPS.length ? p.done : -1;
  const label = (i: Json) => (i === cur && p.as ? p.as : STEPS[i]);
  return (
    <ol className="ostep" aria-label="مراحل سفارش" style={{ '--t': `var(--${p.tone})` }}>
      {STEPS.map((_, i) => {
        const state = i < p.done ? 'done' : i === cur ? 'cur' : 'todo';
        return (
          <li key={i} className={state} aria-current={state === 'cur' ? 'step' : undefined}>
            <span className="dot" aria-hidden="true">
              {state === 'done' ? (
                <Check size={14} strokeWidth={3} />
              ) : state === 'cur' ? (
                <NodeIcon tone={p.tone} status={status} />
              ) : null}
            </span>
            <span>{label(i)}</span>
          </li>
        );
      })}
    </ol>
  );
}

export const needsAttention = (o: AdminOrderRow) => !!o.needs_review || ATTENTION.includes(o.status);
export const GROUPS: Record<string, (o: AdminOrderRow) => boolean> = {
  all: () => true,
  done: (o: AdminOrderRow) => o.status === 'completed',
  progress: (o: AdminOrderRow) => IN_PROGRESS.includes(o.status),
  attention: needsAttention,
  closed: (o: AdminOrderRow) => CLOSED.includes(o.status),
};
export const SORTS: Record<string, (a: AdminOrderRow, b: AdminOrderRow) => number> = {
  new: (a: AdminOrderRow, b: AdminOrderRow) => String(b.created_at).localeCompare(String(a.created_at)),
  old: (a: AdminOrderRow, b: AdminOrderRow) => String(a.created_at).localeCompare(String(b.created_at)),
  high: (a: AdminOrderRow, b: AdminOrderRow) => Number(b.total || 0) - Number(a.total || 0),
};
