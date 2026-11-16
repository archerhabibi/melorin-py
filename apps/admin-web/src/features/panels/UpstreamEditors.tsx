import type { ReactNode } from 'react';
import { useState } from 'react';
import { ChevronDown, Plus, RotateCcw, Trash2, X } from 'lucide-react';
import { Field } from '../../shared/kit.tsx';
import type { Json } from '../../shared/types.ts';

// ---------- settings ----------
export function Fold({
  title,
  hint,
  badge,
  children,
  defaultOpen = false,
  Icon,
}: {
  title?: Json;
  hint?: Json;
  badge?: Json;
  children?: ReactNode;
  defaultOpen?: Json;
  Icon?: Json;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-xl border border-[var(--hair)]">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-xs font-bold"
      >
        {Icon && <Icon size={14} className="text-[var(--mu)]" />}
        {title}
        {badge}
        <ChevronDown size={14} className={`mr-auto text-[var(--mu)] ${open ? '' : '-rotate-90'}`} />
      </button>
      {open && (
        <div className="space-y-4 border-t border-[var(--hair)] px-3 py-3">
          {hint && <p className="text-[11px] leading-5 text-[var(--mu)]">{hint}</p>}
          {children}
        </div>
      )}
    </div>
  );
}

/** Text override: empty = adapter default (shown as placeholder), a reset button appears once it is changed. */
export function TextOverride({
  label,
  def,
  value,
  onChange,
  error,
  hint,
  ltr = false,
}: {
  label?: Json;
  def?: Json;
  value?: Json;
  onChange?: Json;
  error?: Json;
  hint?: Json;
  ltr?: Json;
}) {
  const changed = !!(value ?? '').trim() && value.trim() !== def;
  return (
    <Field label={label} error={error} hint={hint}>
      <div className="relative">
        <input
          dir={ltr ? 'ltr' : 'auto'}
          spellCheck={false}
          className={`inp ${changed ? '!pl-9' : ''}`}
          value={value ?? ''}
          placeholder={def}
          onChange={(e) => onChange(e.target.value)}
        />
        {changed && (
          <button
            type="button"
            aria-label={`بازگشت به پیش‌فرض: ${def}`}
            title={`بازگشت به پیش‌فرض: ${def}`}
            onClick={() => onChange('')}
            className="absolute left-2 top-1/2 -translate-y-1/2 text-[var(--mu)] hover:text-[var(--tx)]"
          >
            <RotateCcw size={14} />
          </button>
        )}
      </div>
    </Field>
  );
}

export function WordChips({ values, onChange, placeholder }: { values?: Json; onChange?: Json; placeholder?: Json }) {
  const [t, setT] = useState('');
  const add = () => {
    const w = t.trim();
    if (w && !values.includes(w)) onChange([...values, w]);
    setT('');
  };
  return (
    <div className="inp flex flex-wrap items-center gap-1.5 !py-1.5">
      {values.map((w: Json) => (
        <span
          key={w}
          className="inline-flex items-center gap-1 rounded-md bg-[var(--mb)] px-2 py-0.5 text-xs font-bold"
        >
          {w}
          <button type="button" aria-label={`حذف ${w}`} onClick={() => onChange(values.filter((x: Json) => x !== w))}>
            <X size={12} />
          </button>
        </span>
      ))}
      <input
        dir="auto"
        className="min-w-[8rem] flex-1 bg-transparent py-1 text-sm outline-hidden"
        value={t}
        placeholder={values.length ? '' : placeholder}
        onChange={(e) => setT(e.target.value)}
        onBlur={add}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ',' || e.key === '،') {
            e.preventDefault();
            add();
          } else if (e.key === 'Backspace' && !t && values.length) onChange(values.slice(0, -1));
        }}
      />
    </div>
  );
}

export function PlansEditor({ plans, onChange, error }: { plans?: Json; onChange?: Json; error?: Json }) {
  const upd = (i: Json, k: Json, v: Json) =>
    onChange(plans.map((p: Json, j: Json) => (j === i ? { ...p, [k]: v } : p)));
  return (
    <div className="space-y-2">
      {plans.length === 0 && (
        <p className="text-[11px] leading-5 text-[var(--mu)]">
          بدون پلن دستی: دکمه‌ی پلن از روی متن خودِ ربات والد (مثل «10 گیگ یک ماهه 60,000 تومان») خوانده می‌شود. فقط اگر
          متن دکمه‌ها غیرعادی است پلن دستی تعریف کنید.
        </p>
      )}
      {plans.map((p: Json, i: Json) => (
        <div key={i} className="grid grid-cols-[5.5rem_4.5rem_1fr_auto] items-end gap-2">
          <Field label={i === 0 ? 'حجم (GB)' : ' '}>
            <input
              dir="ltr"
              inputMode="decimal"
              className="inp"
              aria-label={`حجم پلن ${i + 1}`}
              value={p.traffic_gb}
              placeholder="10"
              onChange={(e) => upd(i, 'traffic_gb', e.target.value.replace(/[^\d.٫۰-۹٠-٩]/g, ''))}
            />
          </Field>
          <Field label={i === 0 ? 'ماه' : ' '}>
            <input
              dir="ltr"
              inputMode="numeric"
              className="inp"
              aria-label={`ماه پلن ${i + 1}`}
              value={p.months}
              placeholder="1"
              onChange={(e) => upd(i, 'months', e.target.value.replace(/[^\d۰-۹٠-٩]/g, ''))}
            />
          </Field>
          <Field label={i === 0 ? 'متن دکمه‌ی پلن در ربات' : ' '}>
            <input
              dir="auto"
              className="inp"
              aria-label={`متن دکمه پلن ${i + 1}`}
              value={p.label}
              placeholder="10 گیگ یک ماهه"
              onChange={(e) => upd(i, 'label', e.target.value)}
            />
          </Field>
          <button
            type="button"
            className="btn btn-g mb-0.5 !px-2"
            aria-label={`حذف پلن ${i + 1}`}
            onClick={() => onChange(plans.filter((_: Json, j: Json) => j !== i))}
          >
            <Trash2 size={14} />
          </button>
        </div>
      ))}
      {error && <p className="text-[11px] text-[var(--bd)]">{error}</p>}
      <button
        type="button"
        className="btn btn-g"
        onClick={() => onChange([...plans, { traffic_gb: '', months: '1', label: '' }])}
      >
        <Plus size={13} />
        افزودن پلن
      </button>
    </div>
  );
}
