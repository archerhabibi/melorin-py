import type { ReactNode } from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Trash2 } from 'lucide-react';
import { confirmDialog, noticeDialog } from './ui.tsx';
import type { CallFn, Json, Rec } from './types.ts';
import { num } from './kitFormat.ts';

/** Chip list: first `max` items, then "+n" overflow badge. */
export function ChipList({ items = [], max = 3, renderItem }: { items?: Json; max?: Json; renderItem?: Json }) {
  return (
    <>
      {items.slice(0, max).map(renderItem)}
      {items.length > max && <span className="text-[11px] text-[var(--mu)]">+{num(items.length - max)}</span>}
    </>
  );
}

/** Readable message of an already-parsed API error body (`{error:{message}}`, `{detail}` or FastAPI's 422 list). */
export function errMsg(body: unknown, fallback: string): string {
  const d = body as { detail?: unknown; error?: { message?: unknown } } | null | undefined;
  const det = d?.detail;
  const first = Array.isArray(det) ? (det[0] as { msg?: unknown } | undefined)?.msg : undefined;
  const fromDetail =
    typeof det === 'string'
      ? det
      : typeof (det as { message?: unknown } | undefined)?.message === 'string'
        ? (det as { message: string }).message
        : null;
  return (
    (typeof d?.error?.message === 'string' && d.error.message) ||
    fromDetail ||
    (typeof first === 'string' && first.replace(/^Value error, /, '')) ||
    fallback
  );
}

export async function errText(r: Json, fallback: Json) {
  try {
    return errMsg(await r.json(), fallback);
  } catch {
    return fallback;
  }
}

/** Red "delete" control used by cards, rows and drawer footers (same look everywhere). */
export function DeleteButton({
  label = 'حذف',
  compact = false,
  busy = false,
  onClick,
  className = '',
}: {
  label?: Json;
  compact?: Json;
  busy?: Json;
  onClick?: Json;
  className?: string;
}) {
  return (
    <button
      type="button"
      className={`btn btn-g btn-d ${compact ? '!px-2' : ''} ${className}`}
      disabled={busy}
      aria-label={label}
      title={label}
      onClick={onClick}
    >
      <Trash2 size={13} />
      {!compact && label}
    </button>
  );
}

/** Confirm → DELETE → report. The Core answers 409 with a plain reason when the item has history; that reason is shown in a dialog. Resolves true only when deleted. */
export async function removeEntity(call: CallFn, path: string, { title, message, done, toast }: Json) {
  if (!(await confirmDialog(message, { title, danger: true, ok: 'حذف دائمی' }))) return false;
  try {
    const r = await call(path, { method: 'DELETE' });
    if (!r.ok) {
      const why = await errText(r, 'حذف ناموفق بود');
      if (r.status === 409) await noticeDialog(why, { title: 'حذف ممکن نیست' });
      else toast(why);
      return false;
    }
  } catch {
    toast('ارتباط با سرور برقرار نشد');
    return false;
  }
  toast(done);
  return true;
}

export function useAlive() {
  const a = useRef(true);
  useEffect(
    () => () => {
      a.current = false;
    },
    [],
  );
  return a;
}

/** Fetch a list endpoint once (and on reload). rows === null while loading. */
/** Fetch a list; pass `{ skip: true }` on screens that do not need this endpoint (lazy-loading #3). */
export function useRows<T = Rec>(call: CallFn, path: string, { skip = false } = {}) {
  const [rows, setRows] = useState<T[] | null>(skip ? [] : null);
  const [failed, setFailed] = useState(false);
  const alive = useAlive();
  const load = useCallback(async () => {
    if (!path || skip) return;
    try {
      const r = await call(path);
      if (!r.ok) throw 0;
      const d = await r.json();
      if (alive.current) {
        setRows(Array.isArray(d) ? d : d.items || []);
        setFailed(false);
      }
    } catch {
      if (alive.current) {
        setFailed(true);
        setRows((x) => x || []);
      }
    }
  }, [path, skip]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!skip) load();
  }, [load]); // eslint-disable-line react-hooks/exhaustive-deps
  return { rows: skip ? [] : rows, failed, load: skip ? () => Promise.resolve() : load };
}

/** Page navigation strip. Renders nothing when all items fit on one page. */
export function Paginator({
  page,
  setPage,
  total,
  pageSize = 20,
}: {
  page?: Json;
  setPage?: Json;
  total?: Json;
  pageSize?: Json;
}) {
  const pages = Math.ceil(total / pageSize);
  if (pages <= 1) return null;
  const from = page * pageSize + 1;
  const to = Math.min(total, (page + 1) * pageSize);
  return (
    <nav aria-label="صفحه‌بندی" className="flex flex-col items-center gap-1.5 pt-3">
      <div className="flex items-center gap-3">
        <button
          className="btn btn-g !py-1.5 !text-xs"
          aria-label="صفحه قبل"
          disabled={page === 0}
          onClick={() => setPage((p: Json) => p - 1)}
        >
          «
        </button>
        <span className="text-xs text-[var(--mu)]" aria-current="page">
          {num(page + 1)} / {num(pages)}
        </span>
        <button
          className="btn btn-g !py-1.5 !text-xs"
          aria-label="صفحه بعد"
          disabled={page >= pages - 1}
          onClick={() => setPage((p: Json) => p + 1)}
        >
          »
        </button>
      </div>
      <p className="text-[11px] text-[var(--mu)]">
        نمایش {num(from)} تا {num(to)} از {num(total)}
      </p>
    </nav>
  );
}

export function Field({
  label,
  hint,
  error,
  children,
}: {
  label?: Json;
  hint?: Json;
  error?: Json;
  children?: ReactNode;
}) {
  return (
    <label className="block text-xs font-bold text-[var(--mu)]">
      {label}
      <div className="mt-1.5 font-normal">{children}</div>
      {(error || hint) && (
        <span
          className={`mt-1 block text-[11px] font-normal leading-5 ${error ? 'text-[var(--bd)]' : 'text-[var(--mu)]'}`}
        >
          {error || hint}
        </span>
      )}
    </label>
  );
}
export function Switch({
  checked,
  onChange,
  disabled,
  label,
  title,
}: {
  checked?: Json;
  onChange?: Json;
  disabled?: Json;
  label?: Json;
  title?: Json;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      title={title}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className="pv-sw disabled:opacity-50"
      data-on={checked}
    >
      <span />
    </button>
  );
}
export function Toggle({
  checked,
  onChange,
  label,
  hint,
}: {
  checked?: Json;
  onChange?: Json;
  label?: Json;
  hint?: Json;
}) {
  return (
    <div className="flex items-start gap-3">
      <Switch checked={checked} onChange={onChange} label={label} />
      <span className="text-xs">
        <b>{label}</b>
        {hint && <span className="mt-0.5 block font-normal leading-5 text-[var(--mu)]">{hint}</span>}
      </span>
    </div>
  );
}
export function Segmented({
  value,
  onChange,
  options,
  label,
}: {
  value?: Json;
  onChange?: Json;
  options?: Json;
  label?: Json;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="pv-seg">
      {options.map(([v, l]: Json) => (
        <button
          key={v}
          type="button"
          role="radio"
          aria-checked={value === v}
          className={value === v ? 'on' : ''}
          onClick={() => onChange(v)}
        >
          {l}
        </button>
      ))}
    </div>
  );
}

export function Empty({
  Icon,
  title,
  text,
  children,
}: {
  Icon?: Json;
  title?: Json;
  text?: Json;
  children?: ReactNode;
}) {
  return (
    <div className="empty rise">
      <span className="tile h-16 w-16 bg-[var(--mb)] text-[var(--mu)]">
        <Icon size={28} />
      </span>
      <h3 className="text-lg font-extrabold">{title}</h3>
      <p className="max-w-md text-sm leading-7 text-[var(--mu)]">{text}</p>
      {children}
    </div>
  );
}
export const ErrorBar = ({ children, onRetry }: { children?: ReactNode; onRetry?: Json }) => (
  <p role="alert" className="flex items-center gap-2 rounded-xl bg-[var(--bdb)] p-3 text-sm text-[var(--bd)]">
    {children}
    {onRetry && (
      <button className="font-extrabold underline" onClick={onRetry}>
        تلاش دوباره
      </button>
    )}
  </p>
);

export * from './kitFormat.ts';
export * from './kitDisplay.tsx';
export * from './kitFilters.tsx';
export * from './kitOverlays.tsx';
