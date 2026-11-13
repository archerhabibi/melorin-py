// Rules of the Bank SMS auto-verification screen shared by admin-web (main store) and store-web (reseller store).
// Core decides every match; these helpers only map the stored source to a form and the form back to the PUT body.
import { toEn } from './format.js';

/** Message status -> Persian label (the colour class is per app). */
export const SMS_STATUS_LABEL = {
  matched: 'شارژ شد',
  unmatched: 'در انتظار رسید',
  ambiguous: 'نیاز به بررسی',
  ignored: 'نادیده',
  unparsed: 'نامفهوم',
};

/** "" -> null, otherwise the integer (Persian digits accepted). */
export const toInt = (s) => {
  const t = toEn(s).replace(/\D/g, '');
  return t === '' ? null : Number(t);
};

export function formFromSource(source) {
  const s = source;
  return {
    auto_verify: !!s.auto_verify,
    is_enabled: s.configured ? !!s.is_enabled : true,
    senders: (s.senders || []).join('\n'),
    window_minutes: String(s.settings.window_minutes),
    time_tolerance_minutes: String(s.settings.time_tolerance_minutes),
    require_claimed_time: !!s.settings.require_claimed_time,
    max_auto_amount_rial: s.settings.max_auto_amount_rial ? String(s.settings.max_auto_amount_rial) : '',
    account_number: s.settings.account_number || '',
  };
}

export function sourceBody(form) {
  return {
    is_enabled: form.is_enabled,
    auto_verify: form.auto_verify,
    senders: form.senders
      .split(/[\n,]/)
      .map((x) => x.trim())
      .filter(Boolean),
    settings: {
      window_minutes: toInt(form.window_minutes),
      time_tolerance_minutes: toInt(form.time_tolerance_minutes),
      require_claimed_time: form.require_claimed_time,
      max_auto_amount_rial: toInt(form.max_auto_amount_rial),
      account_number: String(form.account_number).replace(/\s/g, '') || null,
    },
  };
}
