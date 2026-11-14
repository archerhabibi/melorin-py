// Which admin screens a role may open. The server is the authority (apps/api/melorin/domain/admin_access.py decides every
// request); this table only hides screens a role could not use anyway, so nobody meets a wall of 403s.
// Keep SECTION_AREA in step with the nav in App.tsx (tests/admin-access.test.js fails when a screen has no area).

/** Section key (Persian label used by the router) -> permission area. Sections not listed are owner-only. */
export const SECTION_AREA: Record<string, string> = {
  داشبورد: 'overview',
  'گزارشات و نمودارها': 'reports',
  سفارش‌ها: 'orders',
  پرداخت‌ها: 'payments',
  'اکانت‌های VPN': 'customers',
  تیکت‌ها: 'support',
  کاربران: 'customers',
  فروشگاه‌ها: 'resellers',
  نمایندگان: 'resellers',
  'درخواست‌های نمایندگی': 'resellers',
  'کارهای دستی': 'customers',
  'پیام همگانی': 'customers',
  'مرکز رویداد': 'customers',
  کوپن‌ها: 'catalog',
  'برنامه‌های معرفی': 'catalog',
  'باشگاه مشتریان': 'catalog',
  'پنل‌ها و سرورها': 'infrastructure',
  'اپراتور پنل فروشگاه': 'infrastructure',
  'بسته‌های فروش': 'catalog',
  'محصولات VPN': 'catalog',
  'سلامت زیرساخت': 'infrastructure',
  'عملیات پنل': 'infrastructure',
  'عملیات گروهی': 'infrastructure',
  'حجم فروشگاه‌ها': 'infrastructure',
  تنظیمات: 'system',
  'دکمه‌های تلگرام': 'system',
  ممیزی: 'audit',
  هویت: 'customers',
  'تیم مدیریت': 'admins',
  'حساب من': 'self',
};

/** ``undefined`` = permissions not loaded yet (show everything, the server still enforces); ``[]`` = no access. */
export type Permissions = string[] | undefined;

export const can = (perms: Permissions, area: string, write = false): boolean => {
  if (perms === undefined) return true;
  const granted = perms.find((p) => p.startsWith(`${area}:`));
  if (!granted) return false;
  return !write || granted.endsWith(':rw');
};

export const sectionAllowed = (perms: Permissions, section: string): boolean =>
  can(perms, SECTION_AREA[section] ?? 'system');

/** True when the role may change things in the area (used to hide buttons a viewer cannot use). */
export const canWrite = (perms: Permissions, section: string): boolean =>
  can(perms, SECTION_AREA[section] ?? 'system', true);

export const ROLE_TONE: Record<string, string> = {
  owner: 'in',
  manager: 'ok',
  finance: 'wn',
  support: 'ac',
  viewer: 'mu',
};

export const AREA_LABEL: Record<string, string> = {
  overview: 'نمای کلی',
  reports: 'گزارش‌ها',
  orders: 'سفارش‌ها',
  payments: 'پرداخت‌ها',
  catalog: 'محصولات و تخفیف',
  infrastructure: 'زیرساخت',
  resellers: 'نمایندگان و فروشگاه‌ها',
  customers: 'مشتریان',
  support: 'پشتیبانی',
  audit: 'ممیزی',
  system: 'تنظیمات سیستم',
  admins: 'مدیریت ادمین‌ها',
};

/** Apply an API error code from the admin-team endpoints to a human message (the server message is the fallback). */
export const TEAM_ERRORS: Record<string, string> = {
  ADMIN_ROLE_FORBIDDEN: 'نقش شما اجازه‌ی این کار را ندارد.',
  SELF_CHANGE_FORBIDDEN: 'این کار روی حساب خودتان ممکن نیست؛ از مالک دیگری بخواهید.',
  LAST_OWNER: 'دست‌کم یک مالک فعال باید باقی بماند.',
  ADMIN_EXISTS: 'این ایمیل از قبل ادمین است.',
  EMAIL_IN_USE_BY_CUSTOMER: 'این ایمیل به یک حساب مشتری متصل است؛ از ایمیل دیگری استفاده کنید.',
  RATE_LIMITED: 'تعداد درخواست‌ها زیاد است. کمی بعد تلاش کنید.',
};
