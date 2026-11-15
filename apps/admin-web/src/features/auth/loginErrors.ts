// Admin sign-in failures → what the person should see and where.
//
// The API answers a failed sign-in with { error: { code, message } }. Before this module every code except two was shown as
// "wrong e-mail or password", so a stale authenticator code, a throttled account or a dead network all looked like a wrong
// password. Each failure now has its own message, its own colour and its own place on the form:
//
//   credentials  red     under the form, e-mail + password fields marked invalid
//   totp         amber   directly under the TOTP field, which is cleared and focused for a fresh code
//   form         amber   a general notice (throttling, network, server, IP allow-list ...)

export type LoginChannel = 'password' | 'google';
/** Which part of the form the failure belongs to. */
export type FailureArea = 'credentials' | 'totp' | 'form';
export type FailureTone = 'danger' | 'warning';

export interface LoginFailure {
  /** Stable API (or client-side) error code. */
  code: string;
  area: FailureArea;
  tone: FailureTone;
  /** One short sentence: what went wrong. */
  title: string;
  /** What to do next. */
  hint?: string;
  /** The typed one-time code is useless now: clear it and focus the field. */
  clearTotp?: boolean;
}

/** An error carrying the API code (or a client-side code such as NETWORK_ERROR) and the HTTP status, 0 when unreachable. */
export class LoginRequestError extends Error {
  readonly status: number;
  constructor(code: string, status = 0) {
    super(code);
    this.name = 'LoginRequestError';
    this.status = status;
  }
  get code(): string {
    return this.message;
  }
}

/** API error code of a failed response, or a client-side code derived from the HTTP status. */
export function codeFromResponse(status: number, payload: unknown, fallback: string): string {
  const body = (payload ?? {}) as { error?: { code?: unknown }; code?: unknown };
  const code = body.error?.code || body.code;
  if (typeof code === 'string' && code) return code;
  if (status === 429) return 'RATE_LIMITED';
  if (status >= 500) return 'SERVER_ERROR';
  return fallback;
}

/** Persian (۰-۹) and Arabic-Indic (٠-٩) digits → ASCII, so a code typed on a Persian keyboard still works. */
const toAsciiDigits = (v: string) =>
  v.replace(/[۰-۹٠-٩]/g, (ch) => String(ch.charCodeAt(0) - (ch.charCodeAt(0) >= 0x06f0 ? 0x06f0 : 0x0660)));

/** Keep only the digits of a one-time code: pasted "452 648" or "452-648" becomes "452648". */
export function sanitizeTotp(raw: string): string {
  return toAsciiDigits(String(raw ?? ''))
    .replace(/\D+/g, '')
    .slice(0, 8);
}

const BOOTSTRAP_2FA = 'برای ادمین ابتدا TOTP را با مسیر bootstrap امن فعال کنید.';

const TOTP_HINT_NEW_CODE =
  'کد جدید را از برنامهٔ احراز هویت وارد کنید. اگر چند بار تکرار شد، ساعت گوشی را روی «زمان خودکار» بگذارید.';

/** Failures that are the same on every sign-in channel. */
function common(code: string, status: number): LoginFailure | null {
  switch (code) {
    case 'TOTP_REQUIRED':
      return {
        code,
        area: 'totp',
        tone: 'warning',
        title: 'کد TOTP را وارد کنید.',
        hint: 'کد ۶ رقمی را از برنامهٔ احراز هویت (مثل Google Authenticator) بردارید.',
      };
    case 'TOTP_INVALID':
      return {
        code,
        area: 'totp',
        tone: 'warning',
        title: 'کد TOTP نادرست یا منقضی است.',
        hint: `ایمیل و رمز عبور درست بود. ${TOTP_HINT_NEW_CODE}`,
        clearTotp: true,
      };
    case 'TOTP_REPLAYED':
      return {
        code,
        area: 'totp',
        tone: 'warning',
        title: 'این کد TOTP قبلاً استفاده شده است.',
        hint: 'تا ساخته‌شدن کد بعدی (حداکثر ۳۰ ثانیه) صبر کنید و کد جدید را وارد کنید.',
        clearTotp: true,
      };
    case 'ADMIN_2FA_REQUIRED':
      return { code, area: 'form', tone: 'warning', title: BOOTSTRAP_2FA };
    case 'ACCOUNT_LOGIN_THROTTLED':
      return {
        code,
        area: 'form',
        tone: 'warning',
        title: 'تلاش‌های ورود برای این حساب موقتاً محدود شده است.',
        hint: 'حدود ۱۵ دقیقه صبر کنید و دوباره تلاش کنید.',
      };
    case 'RATE_LIMITED':
      return {
        code,
        area: 'form',
        tone: 'warning',
        title: 'تعداد درخواست‌ها زیاد است.',
        hint: 'یک دقیقه صبر کنید و دوباره تلاش کنید.',
      };
    case 'ADMIN_IP_NOT_ALLOWED':
    case 'IP_NOT_ALLOWED':
      return {
        code,
        area: 'form',
        tone: 'danger',
        title: 'دسترسی ادمین از این IP مجاز نیست.',
        hint: 'از شبکهٔ مجاز وارد شوید یا IP را در فهرست مجاز اضافه کنید.',
      };
    case 'NETWORK_ERROR':
      return {
        code,
        area: 'form',
        tone: 'warning',
        title: 'ارتباط با سرور برقرار نشد.',
        hint: 'اینترنت یا VPN را بررسی کنید و دوباره تلاش کنید.',
      };
    case 'SERVER_ERROR':
      return {
        code,
        area: 'form',
        tone: 'danger',
        title: 'سرور موقتاً پاسخ نمی‌دهد.',
        hint: 'کمی بعد دوباره تلاش کنید؛ اگر ادامه داشت لاگ سرویس API را بررسی کنید.',
      };
    default:
      return status >= 500 ? common('SERVER_ERROR', status) : null;
  }
}

/** The message, area and tone for one failed sign-in. Unknown codes never pretend the password was wrong. */
export function describeLoginFailure(code: string, status = 0, channel: LoginChannel = 'password'): LoginFailure {
  const shared = common(code, status);
  if (shared) return shared;

  if (channel === 'google') {
    switch (code) {
      case 'NOT_ADMIN':
        return { code, area: 'form', tone: 'danger', title: 'این حساب Google دسترسی ادمین ندارد.' };
      case 'GOOGLE_ADMIN_DISABLED':
        return { code, area: 'form', tone: 'warning', title: 'ورود ادمین با گوگل در تنظیمات غیرفعال شده است.' };
      case 'GOOGLE_NONCE_INVALID':
        return {
          code,
          area: 'form',
          tone: 'warning',
          title: 'نشست ورود منقضی شده بود.',
          hint: 'دوباره روی ورود با گوگل بزنید.',
        };
      case 'GOOGLE_UNREACHABLE':
        return {
          code,
          area: 'form',
          tone: 'warning',
          title: 'ارتباط سرور با گوگل برقرار نشد.',
          hint: 'کمی بعد دوباره تلاش کنید.',
        };
      default:
        return { code, area: 'form', tone: 'danger', title: 'ورود با Google ناموفق بود.', hint: 'دوباره تلاش کنید.' };
    }
  }

  if (code === 'INVALID_CREDENTIALS') {
    return {
      code,
      area: 'credentials',
      tone: 'danger',
      title: 'ایمیل یا رمز عبور نادرست است.',
      hint: 'کیبورد انگلیسی و خاموش‌بودن Caps Lock را بررسی کنید. کد TOTP هنوز بررسی نشده است.',
    };
  }
  return {
    code,
    area: 'form',
    tone: 'danger',
    title: 'ورود ناموفق بود.',
    hint: `دوباره تلاش کنید. اگر تکرار شد، این کد را گزارش دهید: ${code}`,
  };
}

/** Same as describeLoginFailure for anything thrown by the sign-in handlers (API errors, unexpected exceptions). */
export function failureFromError(error: unknown, channel: LoginChannel = 'password'): LoginFailure {
  if (error instanceof LoginRequestError) return describeLoginFailure(error.code, error.status, channel);
  return describeLoginFailure('UNEXPECTED_ERROR', 0, channel);
}
