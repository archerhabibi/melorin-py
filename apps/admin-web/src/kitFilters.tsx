import { num } from './kitFormat.ts';
import { useEffect, useRef } from 'react';
import { LayoutGrid, List, Search, X } from 'lucide-react';
import type { Json, Rec } from './types.ts';

/** Filter pills with live counts: options = [[key, label, count, { warn }]]. */
export function Pills({
  value,
  onChange,
  options,
  label,
  scroll = false,
}: {
  value?: Json;
  onChange?: Json;
  options?: Json;
  label?: Json;
  scroll?: Json;
}) {
  return (
    <div className={`pills ${scroll ? 'pills-scroll' : ''}`} role="group" aria-label={label}>
      {options.map(([k, l, n, o]: Json) => (
        <button
          key={k}
          type="button"
          aria-pressed={value === k}
          className={`pill ${o?.warn && n ? 'warn' : ''}`}
          onClick={() => onChange(value === k && k !== 'all' ? 'all' : k)}
        >
          {l}
          <b className="num">{num(n)}</b>
        </button>
      ))}
    </div>
  );
}
export function SearchBox({
  value,
  onChange,
  placeholder,
  label,
  hotkey = false,
}: {
  value?: Json;
  onChange?: Json;
  placeholder?: Json;
  label?: Json;
  hotkey?: Json;
}) {
  const ref = useRef<Json>(null);
  useEffect(() => {
    if (!hotkey) return undefined;
    const f = (e: Json) => {
      // e.code: the physical key stays "Slash" on the Persian layout too; Shift+Slash is "?" and must not trigger it.
      if (e.key !== '/' && !(e.code === 'Slash' && !e.shiftKey)) return;
      if (e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented) return;
      const t = document.activeElement;
      if (t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || (t as HTMLElement).isContentEditable)) return;
      if (document.querySelector('[role="dialog"]')) return; // a drawer / dialog owns the keyboard
      e.preventDefault();
      ref.current?.focus();
    };
    window.addEventListener('keydown', f);
    return () => window.removeEventListener('keydown', f);
  }, [hotkey]);
  return (
    <label className="relative min-w-[12rem] flex-1 sm:max-w-sm">
      <Search size={15} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[var(--mu)]" />
      <input
        ref={ref}
        aria-label={label}
        className="inp !pr-9"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      {hotkey && !value && (
        <kbd
          aria-hidden="true"
          className="pointer-events-none absolute left-2.5 top-1/2 hidden -translate-y-1/2 rounded-md border border-[var(--ln)] bg-[var(--sf)] px-1.5 text-[11px] font-bold leading-5 text-[var(--mu)] md:block"
        >
          /
        </kbd>
      )}
      {value && (
        <button
          type="button"
          aria-label="پاک‌کردن جستجو"
          className="absolute left-2 top-1/2 -translate-y-1/2 rounded-md p-1 text-[var(--mu)] hover:bg-[var(--mb)]"
          onClick={() => onChange('')}
        >
          <X size={13} />
        </button>
      )}
    </label>
  );
}
export function SortSelect({ value, onChange, options }: { value?: Json; onChange?: Json; options?: Json }) {
  return (
    <select
      aria-label="مرتب‌سازی"
      className="inp !w-auto !py-2 !text-xs font-bold"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      {options.map(([k, l]: Json) => (
        <option key={k} value={k}>
          {l}
        </option>
      ))}
    </select>
  );
}
export function ViewToggle({
  value,
  onChange,
  options,
  disabled,
}: {
  value?: Json;
  onChange?: Json;
  options?: Json;
  disabled?: Json;
}) {
  const I: Rec = { grid: LayoutGrid, table: List, list: List, cards: LayoutGrid };
  return (
    <div className="pv-seg" role="group" aria-label="نحوه نمایش">
      {options.map(([k, l]: Json) => {
        const Ic = I[k] || LayoutGrid;
        return (
          <button
            key={k}
            type="button"
            className={value === k ? 'on' : ''}
            aria-pressed={value === k}
            title={l}
            aria-label={l}
            disabled={disabled}
            onClick={() => onChange(k)}
          >
            <Ic size={14} />
            <span className="hidden sm:inline">{l}</span>
          </button>
        );
      })}
    </div>
  );
}
