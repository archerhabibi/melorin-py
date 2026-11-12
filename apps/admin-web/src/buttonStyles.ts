// Pure logic of the Telegram button-style editor (no React): types of the Core payload, the preview matcher and rule helpers.
// The matcher mirrors melorin.domain.button_style.resolve / tgmain.ui.styled_inline so the live preview shows exactly what
// the bots will send: an exact key beats a prefix, a longer prefix beats a shorter one, the first match wins.

export type StyleName = 'primary' | 'success' | 'danger';
export type Kind = 'inline' | 'reply';
export type Match = 'exact' | 'prefix';

export interface ButtonRule {
  kind: Kind;
  match: Match;
  key: string;
  note: string;
  style: StyleName | null;
  icon: string | null;
  prefix: string;
  suffix: string;
  enabled: boolean;
}

export interface ButtonStyleConfig {
  enabled: boolean;
  rules: ButtonRule[];
}

export interface CatalogItem {
  kind: Kind;
  key: string;
  match: Match;
  label: string;
  group: string;
}

export interface Preset {
  id: string;
  name: string;
  description: string;
  rules: Partial<ButtonRule>[];
}

export interface ButtonStylesPayload {
  config: ButtonStyleConfig;
  catalog: CatalogItem[];
  presets: Preset[];
  styles: { id: StyleName; label: string }[];
  limits: { max_rules: number; max_decor: number; url_key: string };
}

export const MAX_BUTTON_TEXT = 64;
export const URL_KEY = '@url';
export const STYLE_LABEL: Record<StyleName, string> = { primary: 'آبی', success: 'سبز', danger: 'قرمز' };
export const STYLE_ORDER: StyleName[] = ['primary', 'success', 'danger'];

const DIGITS = '۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩';
export const normalizeDigits = (s: string): string =>
  s.replace(/[۰-۹٠-٩]/g, (d) => String(DIGITS.indexOf(d) % 10)).replace(/\s+/g, '');
// Telegram custom-emoji ids are int64 values: no leading zero, at most 19 digits (same rule as the server).
export const isEmojiId = (s: string): boolean => /^[1-9][0-9]{4,18}$/.test(normalizeDigits(s));
export const EMOJI_ID_MESSAGE = 'شناسهٔ ایموجی پریمیوم باید فقط عدد باشد (۵ تا ۱۹ رقم و بدون صفر ابتدایی).';
export const MAX_KEY = 64;
export const MAX_REPLY_TEXT = 100;

export const ruleId = (r: Pick<ButtonRule, 'kind' | 'match' | 'key'>): string => `${r.kind}|${r.match}|${r.key}`;

export function blankRule(partial: Partial<ButtonRule> & Pick<ButtonRule, 'key'>): ButtonRule {
  return {
    kind: 'inline',
    match: 'exact',
    note: '',
    style: null,
    icon: null,
    prefix: '',
    suffix: '',
    enabled: true,
    ...partial,
  };
}

export function fromPreset(preset: Preset): ButtonRule[] {
  return preset.rules.map((r) => blankRule({ ...r, key: r.key ?? '' }));
}

// eslint-disable-next-line no-control-regex
const CONTROL_CHARS = /[\u0000-\u001f\u007f-\u009f]/;

/** Client-side mirror of the server validation, per rule: the first problem in Persian or '' when fine. */
export function ruleProblem(r: ButtonRule, maxDecor: number): string {
  const key = r.key.trim();
  const limit = r.kind === 'reply' ? MAX_REPLY_TEXT : MAX_KEY;
  if (!key) return 'کلید دکمه خالی است.';
  if ([...key].length > limit) return `کلید دکمه از ${limit} نویسه بیشتر است.`;
  if (CONTROL_CHARS.test(key)) return 'کلید نباید خط جدید یا نویسهٔ کنترلی داشته باشد.';
  if (r.kind === 'inline' && /^https?:\/\//.test(key))
    return `کلید باید callback دکمه باشد، نه لینک. برای دکمه‌های لینک از «${URL_KEY}» استفاده کنید.`;
  if (key === URL_KEY && r.match === 'prefix') return `«${URL_KEY}» فقط تطبیق دقیق دارد.`;
  if (r.icon && !isEmojiId(r.icon)) return EMOJI_ID_MESSAGE;
  if ([...r.prefix].length > maxDecor || [...r.suffix].length > maxDecor) return `تزئین حداکثر ${maxDecor} نویسه است.`;
  if (CONTROL_CHARS.test(r.prefix) || CONTROL_CHARS.test(r.suffix))
    return 'تزئین نباید خط جدید یا نویسهٔ کنترلی داشته باشد.';
  const decorated = r.kind === 'inline' && Boolean(r.prefix.trim() || r.suffix.trim());
  if (!r.style && !r.icon && !decorated) return 'حداقل یکی از رنگ، ایموجی یا تزئین را مشخص کنید.';
  return '';
}

/** Order the server uses: exact before prefix, longer keys first. */
const specificity = (a: ButtonRule, b: ButtonRule): number =>
  (a.match === 'exact' ? 0 : 1) - (b.match === 'exact' ? 0 : 1) || b.key.length - a.key.length;

export function resolve(rules: ButtonRule[], kind: Kind, key: string): ButtonRule | undefined {
  const pool = rules.filter((r) => r.kind === kind && r.enabled).sort(specificity);
  return pool.find((r) => (r.match === 'exact' ? r.key === key : key.startsWith(r.key)));
}

export interface RenderedButton {
  text: string;
  style: StyleName | null;
  icon: string | null;
}

export function renderInline(cfg: ButtonStyleConfig, key: string, text: string): RenderedButton {
  const rule = cfg.enabled ? resolve(cfg.rules, 'inline', key) : undefined;
  if (!rule) return { text, style: null, icon: null };
  const decorated = `${rule.prefix.trim() ? rule.prefix : ''}${text}${rule.suffix.trim() ? rule.suffix : ''}`;
  return { text: [...decorated].length <= MAX_BUTTON_TEXT ? decorated : text, style: rule.style, icon: rule.icon };
}

export function renderReply(cfg: ButtonStyleConfig, text: string): RenderedButton {
  const rule = cfg.enabled ? resolve(cfg.rules, 'reply', text) : undefined;
  return { text, style: rule?.style ?? null, icon: rule?.icon ?? null };
}

/** Sample keyboards of the preview: real labels and callback keys of the bots, in the order a customer meets them. */
export const SAMPLE_INLINE: { rows: [string, string][][] } = {
  rows: [
    [
      ['🛒 خرید اکانت', 'menu:plans'],
      ['💰 کیف پول', 'menu:wallet'],
    ],
    [['✅ خرید و پرداخت', 'buy:sample']],
    [
      ['🎫 تیکت‌ها', 'menu:tickets'],
      ['⛔ این من نبودم', 'wld:sample'],
    ],
    [['🌐 حساب من در سایت', URL_KEY]],
    [['🏠 خانه', 'menu:home']],
  ],
};
export const SAMPLE_REPLY: string[][] = [
  ['🛒 خرید اکانت', '🔍 استعلام و تمدید اکانت'],
  ['💰 کیف پول و شارژ حساب', '🌐 حساب من در سایت'],
  ['🎧 پشتیبانی'],
];

/** True when two configs are equal for saving purposes (drives the "unsaved changes" state). */
export const sameConfig = (a: ButtonStyleConfig, b: ButtonStyleConfig): boolean =>
  JSON.stringify(a) === JSON.stringify(b);

/** Payload for PUT / preview: icons normalised to ASCII digits, empty strings dropped to null. */
export function toPayload(cfg: ButtonStyleConfig): ButtonStyleConfig {
  return {
    enabled: cfg.enabled,
    rules: cfg.rules.map((r) => ({
      ...r,
      key: r.key.trim(),
      icon: r.icon ? normalizeDigits(r.icon) : null,
      style: r.style || null,
      prefix: r.prefix.trim() ? r.prefix : '',
      suffix: r.suffix.trim() ? r.suffix : '',
    })),
  };
}
