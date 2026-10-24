// Pure logic of the `upstream_bot` panel form (no React): defaults, parsing, validation, payload building and the
// flow preview. The defaults mirror apps/api/melorin/modules/vpn/adapters/upstream_bot/adapter.py (DEFAULTS); a field
// left empty means "use the adapter default", so only real overrides are stored in the panel config.

export const UB_TEXT = {
  start_command: '/start',
  menu_buy: 'خرید اکانت',
  service_button: 'سرویس اقتصادی',
  confirm_button: 'تایید خرید',
  cancel_button: 'انصراف',
  menu_purchases: 'خریدهای من',
  search_button: 'جستجوی اکانت',
  link_button: 'لینک',
  refund_button: 'مرجوعی اکانت',
  refund_confirm_button: 'تایید میکنم',
};
export const UB_NUM = { status_ttl: 60, step_timeout: 25, delivery_timeout: 60 };
export const UB_RENEW = {
  renew_button: 'تمدید اکانت',
  confirm_button: 'تایید تمدید',
  cancel_button: 'برگشت',
  success_words: ['با موفقیت تمدید'],
  settle_window: 600,
};
export const UB_RENEW_KEYS = ['enabled', 'renew_button', 'confirm_button', 'cancel_button', 'success_words', 'settle_window'];
// Config keys the form owns. Everything else stays in the advanced JSON box so a save never drops it.
export const UB_KEYS = [...Object.keys(UB_TEXT), ...Object.keys(UB_NUM), 'max_price', 'plans', 'renew', 'verify_tls'];

export const PRICE_PRESETS = [50000, 100000, 200000, 500000];

export const emptyUb = () => ({
  bot: '',
  apiId: '',
  apiHash: '',
  session: '',
  maxPrice: '',
  t: {}, // text overrides by config key ('' / missing = default)
  n: {}, // numeric overrides by config key
  plans: [], // [{traffic_gb, months, label}] as strings
  renewOn: true,
  r: {}, // renew text / settle_window overrides
  rWords: [], // renew.success_words override ([] = default)
  rRest: {}, // renew keys the form has no field for
});

const PERSIAN = '۰۱۲۳۴۵۶۷۸۹';
const ARABIC = '٠١٢٣٤٥٦٧٨٩';
export const latin = (s) =>
  String(s ?? '')
    .replace(/[۰-۹]/g, (d) => String(PERSIAN.indexOf(d)))
    .replace(/[٠-٩]/g, (d) => String(ARABIC.indexOf(d)))
    .replace(/٫/g, '.');

/** @name, name, t.me/name, https://t.me/name/ ... -> name ('' when it is not a bot reference). */
export function parseBot(raw) {
  const s = String(raw ?? '')
    .trim()
    .replace(/[?#].*$/, '')
    .replace(/\/+$/, '');
  const m = /^(?:https?:\/\/)?(?:(?:www\.)?(?:t|telegram)\.me\/)?@?([A-Za-z0-9_]+)$/i.exec(s);
  return m ? m[1] : '';
}
export const botUrl = (bot) => `https://t.me/${bot}`;
export const botLooksLikeBot = (bot) => /bot$/i.test(bot);

const isObj = (x) => x && typeof x === 'object' && !Array.isArray(x);

/** Rebuild the form state from a stored panel. */
export function ubFromPanel(p) {
  const c = isObj(p?.config) ? p.config : {},
    ub = emptyUb();
  ub.bot = parseBot(p?.base_url);
  for (const [k, d] of Object.entries(UB_TEXT)) if (typeof c[k] === 'string' && c[k] && c[k] !== d) ub.t[k] = c[k];
  for (const [k, d] of Object.entries(UB_NUM)) if (c[k] != null && Number(c[k]) !== d) ub.n[k] = String(c[k]);
  const mp = parseInt(c.max_price, 10);
  ub.maxPrice = mp > 0 ? String(mp) : '';
  if (Array.isArray(c.plans))
    ub.plans = c.plans.filter(isObj).map((x) => ({
      traffic_gb: x.traffic_gb == null ? '' : String(x.traffic_gb),
      months: x.months == null ? '1' : String(x.months),
      label: x.label == null ? '' : String(x.label),
    }));
  const r = isObj(c.renew) ? c.renew : {};
  ub.renewOn = r.enabled !== false;
  for (const k of ['renew_button', 'confirm_button', 'cancel_button'])
    if (typeof r[k] === 'string' && r[k] && r[k] !== UB_RENEW[k]) ub.r[k] = r[k];
  if (r.settle_window != null && Number(r.settle_window) !== UB_RENEW.settle_window) ub.r.settle_window = String(r.settle_window);
  if (Array.isArray(r.success_words) && r.success_words.length && r.success_words.join('\u0000') !== UB_RENEW.success_words.join('\u0000'))
    ub.rWords = r.success_words.map(String);
  ub.rRest = Object.fromEntries(Object.entries(r).filter(([k]) => !UB_RENEW_KEYS.includes(k)));
  return ub;
}

/** The `config` object sent to the API. `renew.enabled` is always explicit (the adapter's capabilities read it directly). */
export function ubBuildConfig(ub) {
  const cfg = { max_price: parseInt(latin(ub.maxPrice), 10) };
  for (const [k, d] of Object.entries(UB_TEXT)) {
    const v = (ub.t[k] ?? '').trim();
    if (v && v !== d) cfg[k] = v;
  }
  for (const [k, d] of Object.entries(UB_NUM)) {
    const v = latin(ub.n[k] ?? '').trim();
    if (v !== '' && Number(v) !== d) cfg[k] = Number(v);
  }
  if (ub.plans.length)
    cfg.plans = ub.plans.map((p) => ({
      traffic_gb: Number(latin(p.traffic_gb)),
      months: parseInt(latin(p.months), 10),
      label: p.label.trim(),
    }));
  const renew = { ...ub.rRest, enabled: !!ub.renewOn };
  for (const k of ['renew_button', 'confirm_button', 'cancel_button']) {
    const v = (ub.r[k] ?? '').trim();
    if (v && v !== UB_RENEW[k]) renew[k] = v;
  }
  const words = ub.rWords.map((w) => w.trim()).filter(Boolean);
  if (words.length && words.join('\u0000') !== UB_RENEW.success_words.join('\u0000')) renew.success_words = words;
  const sw = latin(ub.r.settle_window ?? '').trim();
  if (sw !== '' && Number(sw) !== UB_RENEW.settle_window) renew.settle_window = Number(sw);
  cfg.renew = renew;
  return cfg;
}

export const ubCredentials = (ub) => ({
  api_id: parseInt(latin(ub.apiId), 10),
  api_hash: latin(ub.apiHash).trim(),
  session: ub.session.replace(/\s+/g, ''),
});

/** Field errors by key (Persian messages). */
export function ubValidate(ub, withCreds) {
  const e = {};
  if (!ub.bot) e.bot = 'نام کاربری ربات والد را وارد کنید (مثال: @parent_bot)';
  else if (!/^[A-Za-z][A-Za-z0-9_]{4,31}$/.test(ub.bot)) e.bot = 'نام کاربری تلگرام باید ۵ تا ۳۲ حرف انگلیسی، عدد یا _ باشد';
  if (withCreds) {
    if (!/^\d{3,12}$/.test(latin(ub.apiId).trim())) e.apiId = 'api_id یک عدد است (از my.telegram.org)';
    if (!/^[0-9a-fA-F]{32}$/.test(latin(ub.apiHash).trim())) e.apiHash = 'api_hash باید ۳۲ کاراکتر هگزادسیمال باشد';
    const s = ub.session.replace(/\s+/g, '');
    if (!s) e.session = 'رشته‌ی session را وارد کنید';
    else if (s.length < 100 || !/^[A-Za-z0-9+/=_-]+$/.test(s))
      e.session = 'session ناقص یا نامعتبر است؛ کل خروجی scripts/upstream_bot_login.py را بچسبانید';
  }
  const price = parseInt(latin(ub.maxPrice), 10);
  if (!(price > 0)) e.maxPrice = 'سقف قیمت اجباری است؛ خرید/تمدید گران‌تر از آن لغو می‌شود';
  if (ub.t.start_command && !ub.t.start_command.trim().startsWith('/')) e.start_command = 'دستور شروع باید با / شروع شود';
  const range = { status_ttl: [1, 3600], step_timeout: [1, 300], delivery_timeout: [1, 900] };
  for (const [k, [lo, hi]] of Object.entries(range)) {
    const v = latin(ub.n[k] ?? '').trim();
    if (v !== '' && !(Number(v) >= lo && Number(v) <= hi)) e[k] = `عددی بین ${lo} و ${hi} ثانیه`;
  }
  const sw = latin(ub.r.settle_window ?? '').trim();
  if (ub.renewOn && sw !== '' && !(Number(sw) >= 1 && Number(sw) <= 86400)) e.settle_window = 'عددی بین ۱ و ۸۶۴۰۰ ثانیه';
  const bad = ub.plans.findIndex((p) => {
    const gb = Number(latin(p.traffic_gb)),
      mo = Number(latin(p.months));
    return !(gb > 0) || !Number.isInteger(mo) || mo < 1 || !p.label.trim();
  });
  if (bad >= 0) e.plans = `پلن ${bad + 1}: حجم (>۰)، ماه (عدد صحیح ≥۱) و متن دکمه‌ی پلن لازم است`;
  return e;
}

const txt = (ub, k) => (ub.t[k] ?? '').trim() || UB_TEXT[k];
const rtxt = (ub, k) => (ub.r[k] ?? '').trim() || UB_RENEW[k];

/** What the userbot will do in the parent bot for every Melorin action, with the configured button texts. */
export function ubFlows(ub) {
  const start = { k: 'cmd', l: txt(ub, 'start_command') };
  const account = [
    start,
    { k: 'btn', l: txt(ub, 'menu_purchases') },
    { k: 'btn', l: txt(ub, 'search_button') },
    { k: 'in', l: 'نام اکانت' },
  ];
  return [
    {
      id: 'buy',
      title: 'خرید',
      steps: [
        start,
        { k: 'btn', l: txt(ub, 'menu_buy') },
        { k: 'btn', l: txt(ub, 'service_button') },
        { k: 'btn', l: 'پلن (حجم + ماه)' },
        { k: 'chk', l: 'قیمت = قیمت پلن و ≤ سقف' },
        { k: 'btn', l: txt(ub, 'confirm_button') },
        { k: 'out', l: 'نام + لینک اشتراک' },
      ],
    },
    { id: 'status', title: 'وضعیت زنده', steps: [...account, { k: 'out', l: 'وضعیت، حجم مصرفی، تاریخ پایان' }] },
    {
      id: 'refund',
      title: 'مرجوعی',
      steps: [
        ...account,
        { k: 'btn', l: txt(ub, 'refund_button') },
        { k: 'btn', l: txt(ub, 'refund_confirm_button') },
        { k: 'out', l: 'برگشت مبلغ به کیف پول ربات' },
      ],
    },
    {
      id: 'renew',
      title: 'تمدید',
      off: !ub.renewOn,
      steps: [
        ...account,
        { k: 'btn', l: rtxt(ub, 'renew_button') },
        { k: 'btn', l: 'تمدید با حجم اولیه' },
        { k: 'chk', l: 'موجودی ≥ قیمت و ≤ سقف' },
        { k: 'btn', l: rtxt(ub, 'confirm_button') },
        { k: 'out', l: 'شروع دوباره از همین لحظه' },
      ],
    },
  ];
}

/** Short facts for the panel card header. */
export function ubSummary(p) {
  const c = isObj(p?.config) ? p.config : {},
    mp = parseInt(c.max_price, 10);
  return {
    bot: parseBot(p?.base_url),
    maxPrice: mp > 0 ? mp : 0,
    renewOn: !(isObj(c.renew) && c.renew.enabled === false),
    plans: Array.isArray(c.plans) ? c.plans.length : 0,
  };
}
