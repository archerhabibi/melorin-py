// دکمه‌های تلگرام: the admin styles the bots' buttons — colour (blue / green / red), Premium custom emoji and a small text
// decoration — with a live Telegram-like preview. Rules are keyed by the button's callback (or its exact text on the reply
// keyboard), so one rule restyles a button in every bot (main store and all reseller bots). Core validates and publishes;
// the bots download the result, and Telegram's own rules apply (custom emoji need a Premium bot owner).
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Info, Paintbrush, Plus, RotateCcw, Save, Send, Sparkles, Trash2 } from 'lucide-react';
import { authFetch } from './api.ts';
import { Empty, ErrorBar, Field, Section, Switch, errText, num } from './kit.tsx';
import { confirmDialog } from './ui.tsx';
import {
  SAMPLE_INLINE,
  SAMPLE_REPLY,
  STYLE_LABEL,
  STYLE_ORDER,
  URL_KEY,
  blankRule,
  fromPreset,
  isEmojiId,
  renderInline,
  renderReply,
  ruleId,
  ruleProblem,
  sameConfig,
  toPayload,
} from './buttonStyles.ts';
import type {
  ButtonRule,
  ButtonStyleConfig,
  ButtonStylesPayload,
  CatalogItem,
  Kind,
  Match,
  RenderedButton,
  StyleName,
} from './buttonStyles.ts';
import type { Toast } from './types.ts';

const EMPTY: ButtonStyleConfig = { enabled: false, rules: [] };

function TgButton({ b }: { b: RenderedButton }) {
  return (
    <span className="tg-btn" data-style={b.style ?? 'none'}>
      {b.icon && (
        <span className="tg-btn-icon" title="ایموجی پریمیوم (در تلگرام به‌صورت ایموجی واقعی نمایش داده می‌شود)">
          ✦
        </span>
      )}
      <span className="truncate">{b.text}</span>
    </span>
  );
}

/** A Telegram-like chat with the sample keyboards, rendered from the draft exactly as the bots would build them. */
function Preview({ cfg }: { cfg: ButtonStyleConfig }) {
  return (
    <div className="tg-phone" aria-label="پیش‌نمایش دکمه‌ها" dir="rtl">
      <div className="tg-bubble">پیش‌نمایش دکمه‌های اینلاین (زیر پیام)</div>
      <div className="tg-kb">
        {SAMPLE_INLINE.rows.map((row, i) => (
          <div key={i} className="tg-row">
            {row.map(([text, key]) => (
              <TgButton key={key + text} b={renderInline(cfg, key, text)} />
            ))}
          </div>
        ))}
      </div>
      <div className="tg-bubble mt-4">پیش‌نمایش کیبورد پایین (منوی اصلی)</div>
      <div className="tg-kb tg-kb-reply">
        {SAMPLE_REPLY.map((row, i) => (
          <div key={i} className="tg-row">
            {row.map((text) => (
              <TgButton key={text} b={renderReply(cfg, text)} />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function StylePicker({
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

function RuleCard({
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

function AddRule({
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

export default function ButtonStylesView({ api, toast }: { api: { base: string }; toast: Toast }) {
  const call = useCallback((p: string, o: RequestInit = {}) => authFetch(api.base, p, o), [api.base]);
  const [data, setData] = useState<ButtonStylesPayload | null>(null);
  const [saved, setSaved] = useState<ButtonStyleConfig>(EMPTY);
  const [cfg, setCfg] = useState<ButtonStyleConfig>(EMPTY);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState<'' | 'save' | 'preview'>('');
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const r = await call('/api/v1/admin/telegram/button-styles');
      if (!r.ok) throw new Error('load');
      const d: ButtonStylesPayload = await r.json();
      setData(d);
      setSaved(d.config);
      setCfg(d.config);
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [call]);
  useEffect(() => {
    load();
  }, [load]);

  const catalogByKey = useMemo(() => new Map((data?.catalog ?? []).map((c) => [ruleId(c), c])), [data]);
  const maxDecor = data?.limits.max_decor ?? 6;
  const maxRules = data?.limits.max_rules ?? 120;
  const dirty = !sameConfig(cfg, saved);
  const problems = cfg.rules.filter((r) => ruleProblem(r, maxDecor)).length;
  const used = useMemo(() => new Set(cfg.rules.map(ruleId)), [cfg.rules]);

  const patch = (id: string, p: Partial<ButtonRule>) =>
    setCfg((c) => ({ ...c, rules: c.rules.map((r) => (ruleId(r) === id ? { ...r, ...p } : r)) }));
  const add = (r: ButtonRule) => {
    if (used.has(ruleId(r))) return toast('برای این دکمه قبلاً قانون ساخته‌اید');
    setCfg((c) => ({ ...c, rules: [...c.rules, r] }));
  };

  const applyPreset = async (id: string) => {
    const preset = data?.presets.find((p) => p.id === id);
    if (!preset) return;
    if (cfg.rules.length) {
      const ok = await confirmDialog(
        `قانون‌های فعلی با الگوی «${preset.name}» جایگزین شود؟ (تا قبل از ذخیره می‌توانید بازگردانید)`,
        {
          title: 'اعمال الگو',
          ok: 'جایگزین کن',
        },
      );
      if (!ok) return;
    }
    setCfg({ enabled: true, rules: fromPreset(preset) });
  };

  const save = async () => {
    setError('');
    setBusy('save');
    try {
      const r = await call('/api/v1/admin/telegram/button-styles', {
        method: 'PUT',
        body: JSON.stringify(toPayload(cfg)),
      });
      if (!r.ok) return setError(await errText(r, 'ذخیره ناموفق بود'));
      const d: ButtonStylesPayload = await r.json();
      setData(d);
      setSaved(d.config);
      setCfg(d.config);
      toast(
        d.config.enabled ? 'ذخیره شد؛ ربات‌ها تا حدود یک دقیقه دیگر اعمال می‌کنند' : 'ذخیره شد (رنگی‌سازی خاموش است)',
      );
    } catch {
      setError('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy('');
    }
  };

  const sendPreview = async () => {
    setError('');
    setBusy('preview');
    try {
      const r = await call('/api/v1/admin/telegram/button-styles/preview', {
        method: 'POST',
        body: JSON.stringify(toPayload(cfg)),
      });
      if (!r.ok) return setError(await errText(r, 'ارسال پیش‌نمایش ناموفق بود'));
      toast('پیش‌نمایش به تلگرام شما ارسال شد');
    } catch {
      setError('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy('');
    }
  };

  if (failed) return <ErrorBar onRetry={load}>دریافت تنظیمات دکمه‌ها ناموفق بود.</ErrorBar>;
  if (!data) return <div className="card p-6 text-sm text-[var(--mu)]">در حال بارگذاری…</div>;

  const titleOf = (r: ButtonRule) => catalogByKey.get(ruleId(r))?.label || r.note || r.key;

  return (
    <div className="space-y-5">
      <Section
        title="رنگی‌سازی دکمه‌های تلگرام"
        hint="رنگ (آبی، سبز، قرمز)، ایموجی پریمیوم و تزئین متن دکمه‌ها را برای ربات اصلی و همهٔ ربات‌های نمایندگان یک‌جا تعیین کنید."
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Switch
              checked={cfg.enabled}
              onChange={(v: boolean) => setCfg({ ...cfg, enabled: v })}
              label="فعال‌سازی رنگی‌سازی دکمه‌ها"
            />
            <span className="text-sm font-bold">{cfg.enabled ? 'فعال' : 'خاموش — دکمه‌ها ساده ارسال می‌شوند'}</span>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn btn-g" disabled={!!busy} onClick={sendPreview}>
              <Send size={15} /> {busy === 'preview' ? 'در حال ارسال…' : 'ارسال نمونه به تلگرام من'}
            </button>
            <button type="button" className="btn btn-g" disabled={!dirty || !!busy} onClick={() => setCfg(saved)}>
              <RotateCcw size={15} /> بازگردانی
            </button>
            <button type="button" className="btn" disabled={!dirty || !!busy || problems > 0} onClick={save}>
              <Save size={15} /> {busy === 'save' ? 'در حال ذخیره…' : 'ذخیره'}
            </button>
          </div>
        </div>
        {dirty && <div className="text-xs font-bold text-[var(--wn)]">تغییرات ذخیره‌نشده دارید.</div>}
        {error && <ErrorBar>{error}</ErrorBar>}
        <div className="flex items-start gap-2 rounded-xl border border-[var(--ln)] p-3 text-[11px] leading-6 text-[var(--mu)]">
          <Info size={14} className="mt-1 shrink-0" />
          <span>
            رنگ دکمه‌ها (Bot API 9.4) برای همهٔ کاربران نمایش داده می‌شود. ایموجی پریمیوم فقط وقتی دیده می‌شود که صاحب
            ربات اشتراک Telegram Premium داشته باشد (یا ربات نام کاربری اضافه از Fragment خریده باشد)؛ در غیر این صورت
            تلگرام آن را نشان نمی‌دهد. اگر تلگرام دکمهٔ رنگی را نپذیرد، ربات همان پیام را بدون رنگ ارسال می‌کند و پیامی
            گم نمی‌شود.
          </span>
        </div>
      </Section>

      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="space-y-5">
          <Section
            title="الگوهای آماده"
            hint="با یک کلیک همهٔ قانون‌ها را از یک الگو بسازید و بعد جزئیات را تغییر دهید."
          >
            <div className="grid gap-3 sm:grid-cols-3">
              {data.presets.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className="card p-3 text-start transition hover:ring-2 hover:ring-[var(--ac)]"
                  onClick={() => applyPreset(p.id)}
                >
                  <span className="flex items-center gap-1.5 text-sm font-extrabold">
                    <Sparkles size={14} /> {p.name}
                  </span>
                  <span className="mt-1 block text-[11px] leading-5 text-[var(--mu)]">{p.description}</span>
                </button>
              ))}
            </div>
          </Section>

          <Section
            title={`قانون‌ها (${num(cfg.rules.length)} از ${num(maxRules)})`}
            hint="قانون دقیق بر قانون پیشوندی و پیشوند بلندتر بر کوتاه‌تر مقدم است."
          >
            <AddRule catalog={data.catalog} used={used} disabled={cfg.rules.length >= maxRules} onAdd={add} />
            {cfg.rules.length === 0 ? (
              <Empty
                Icon={Paintbrush}
                title="هنوز قانونی ندارید"
                text="یک الگو را اعمال کنید یا دکمه‌ای را از فهرست بالا اضافه کنید."
              />
            ) : (
              <ul className="space-y-3">
                {cfg.rules.map((r) => (
                  <RuleCard
                    key={ruleId(r)}
                    rule={r}
                    title={titleOf(r)}
                    maxDecor={maxDecor}
                    onChange={(p) => patch(ruleId(r), p)}
                    onRemove={() => setCfg((c) => ({ ...c, rules: c.rules.filter((x) => ruleId(x) !== ruleId(r)) }))}
                  />
                ))}
              </ul>
            )}
          </Section>
        </div>

        <div className="lg:sticky lg:top-4">
          <Section
            title="پیش‌نمایش زنده"
            hint={
              cfg.enabled
                ? 'همان چیزی که مشتری در تلگرام می‌بیند.'
                : 'رنگی‌سازی خاموش است؛ دکمه‌ها ساده نمایش داده می‌شوند.'
            }
          >
            <Preview cfg={cfg} />
          </Section>
        </div>
      </div>
    </div>
  );
}
