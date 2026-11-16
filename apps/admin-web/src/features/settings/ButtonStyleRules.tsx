import { useState } from 'react';
import { Info, Plus, Trash2 } from 'lucide-react';
import { Field, Switch, num } from '../../shared/kit.tsx';
import { STYLE_LABEL, STYLE_ORDER, URL_KEY, blankRule, isEmojiId, ruleId, ruleProblem } from './buttonStyles.ts';
import type { ButtonRule, CatalogItem, Kind, Match, StyleName } from './buttonStyles.ts';

export function StylePicker({
  value,
  onChange,
  label,
}: {
  value: StyleName | null;
  onChange: (v: StyleName | null) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-1.5">
      {[null, ...STYLE_ORDER].map((s) => (
        <button
          key={s ?? 'none'}
          type="button"
          role="radio"
          aria-checked={value === s}
          onClick={() => onChange(s)}
          className={`tg-swatch ${value === s ? 'is-on' : ''}`}
          data-style={s ?? 'none'}
        >
          {s ? STYLE_LABEL[s] : 'بدون رنگ'}
        </button>
      ))}
    </div>
  );
}

export function RuleCard({
  rule,
  title,
  maxDecor,
  onChange,
  onRemove,
}: {
  rule: ButtonRule;
  title: string;
  maxDecor: number;
  onChange: (patch: Partial<ButtonRule>) => void;
  onRemove: () => void;
}) {
  const problem = ruleProblem(rule, maxDecor);
  const isReply = rule.kind === 'reply';
  return (
    <li className={`card space-y-3 p-4 ${rule.enabled ? '' : 'opacity-60'}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-extrabold">{title}</div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px]">
            <span className="badge b-mu">{isReply ? 'کیبورد پایین' : 'دکمهٔ اینلاین'}</span>
            <span className="badge b-mu">{rule.match === 'prefix' ? 'پیشوندی' : 'دقیق'}</span>
            <code dir="ltr" className="text-[var(--mu)]">
              {rule.key}
            </code>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Switch
            checked={rule.enabled}
            onChange={(v: boolean) => onChange({ enabled: v })}
            label="فعال بودن این قانون"
          />
          <button type="button" className="btn btn-g !px-2 !py-1" aria-label="حذف قانون" onClick={onRemove}>
            <Trash2 size={15} />
          </button>
        </div>
      </div>
      <Field label="رنگ دکمه">
        <StylePicker value={rule.style} onChange={(style) => onChange({ style })} label="رنگ دکمه" />
      </Field>
      <div className={`grid gap-3 ${isReply ? '' : 'sm:grid-cols-2'}`}>
        <Field
          label="ایموجی پریمیوم (شناسهٔ عددی)"
          hint="شناسهٔ custom emoji از ربات‌هایی مثل @ShowJsonBot؛ فقط برای ربات‌هایی که صاحبشان Premium دارد نمایش داده می‌شود."
          error={rule.icon && !isEmojiId(rule.icon) ? 'شناسه معتبر نیست' : ''}
        >
          <input
            dir="ltr"
            inputMode="numeric"
            spellCheck={false}
            autoComplete="off"
            className="inp font-mono text-xs"
            placeholder="5368324170671202286"
            value={rule.icon ?? ''}
            onChange={(e) => onChange({ icon: e.target.value || null })}
          />
        </Field>
        {!isReply && (
          <div className="grid grid-cols-2 gap-3">
            <Field label="پیشوند" hint={`حداکثر ${num(maxDecor)} نویسه`}>
              <input
                className="inp"
                value={rule.prefix}
                onChange={(e) => onChange({ prefix: e.target.value })}
                placeholder="💎 "
              />
            </Field>
            <Field label="پسوند">
              <input
                className="inp"
                value={rule.suffix}
                onChange={(e) => onChange({ suffix: e.target.value })}
                placeholder=" ✨"
              />
            </Field>
          </div>
        )}
      </div>
      {isReply && (
        <p className="flex items-start gap-1.5 text-[11px] leading-5 text-[var(--mu)]">
          <Info size={13} className="mt-0.5 shrink-0" />
          متن دکمه‌های کیبورد پایین تغییر نمی‌کند، چون ربات منو را از روی همین متن تشخیص می‌دهد؛ فقط رنگ و ایموجی اعمال
          می‌شود.
        </p>
      )}
      {problem && <div className="text-xs text-[var(--bd)]">{problem}</div>}
    </li>
  );
}

export function AddRule({
  catalog,
  used,
  disabled,
  onAdd,
}: {
  catalog: CatalogItem[];
  used: Set<string>;
  disabled: boolean;
  onAdd: (r: ButtonRule) => void;
}) {
  const [pick, setPick] = useState('');
  const [custom, setCustom] = useState(false);
  const [kind, setKind] = useState<Kind>('inline');
  const [match, setMatch] = useState<Match>('prefix');
  const [key, setKey] = useState('');
  const free = catalog.filter((c) => !used.has(ruleId(c)));
  const groups = [...new Set(free.map((c) => c.group))];

  const add = () => {
    if (custom) {
      const k = key.trim();
      if (!k) return;
      // reply texts and the pseudo key @url only ever match exactly (the form's default "prefix" would start them off invalid)
      onAdd(blankRule({ kind, match: kind === 'reply' || k === URL_KEY ? 'exact' : match, key: k, style: 'primary' }));
      setKey('');
      return;
    }
    const item = free.find((c) => ruleId(c) === pick);
    if (!item) return;
    onAdd(blankRule({ kind: item.kind, match: item.match, key: item.key, note: item.label, style: 'primary' }));
    setPick('');
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        {!custom ? (
          <div className="min-w-[14rem] flex-1">
            <Field label="دکمه‌ای را برای رنگی‌کردن انتخاب کنید">
              <select className="inp" value={pick} onChange={(e) => setPick(e.target.value)} disabled={disabled}>
                <option value="">— انتخاب دکمه —</option>
                {groups.map((g) => (
                  <optgroup key={g} label={g}>
                    {free
                      .filter((c) => c.group === g)
                      .map((c) => (
                        <option key={ruleId(c)} value={ruleId(c)}>
                          {c.label}
                        </option>
                      ))}
                  </optgroup>
                ))}
              </select>
            </Field>
          </div>
        ) : (
          <>
            <Field label="نوع">
              <select className="inp" value={kind} onChange={(e) => setKind(e.target.value as Kind)}>
                <option value="inline">اینلاین</option>
                <option value="reply">کیبورد پایین</option>
              </select>
            </Field>
            {kind === 'inline' && (
              <Field label="تطبیق">
                <select className="inp" value={match} onChange={(e) => setMatch(e.target.value as Match)}>
                  <option value="prefix">پیشوندی</option>
                  <option value="exact">دقیق</option>
                </select>
              </Field>
            )}
            <div className="min-w-[12rem] flex-1">
              <Field label={kind === 'reply' ? 'متن دقیق دکمه' : 'callback دکمه'}>
                <input
                  dir="ltr"
                  className="inp font-mono text-xs"
                  value={key}
                  onChange={(e) => setKey(e.target.value)}
                  placeholder="menu:plans"
                />
              </Field>
            </div>
          </>
        )}
        <button type="button" className="btn" disabled={disabled || (custom ? !key.trim() : !pick)} onClick={add}>
          <Plus size={15} /> افزودن
        </button>
      </div>
      <button
        type="button"
        className="text-xs font-bold text-[var(--in)] underline-offset-2 hover:underline"
        onClick={() => setCustom(!custom)}
      >
        {custom ? 'بازگشت به فهرست دکمه‌ها' : 'دکمه در فهرست نیست؟ قانون سفارشی بسازید'}
      </button>
    </div>
  );
}
