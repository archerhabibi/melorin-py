import {
  UB_KEYS,
  botUrl,
  emptyUb,
  ubBot,
  ubBuildConfig,
  ubCredentials,
  ubFromPanel,
  ubValidate,
} from './upstreamBot.ts';
import type { Json, Rec } from '../../shared/types.ts';

// ---------- panel add / edit form ----------
export const EMPTY = {
  kind: 'sanaei',
  name: '',
  url: '',
  auth: 'token',
  token: '',
  user: '',
  pass: '',
  inbounds: [],
  subUrl: '',
  apiStyle: 'auto',
  groups: [],
  tpl: '',
  scope: 'groups',
  verifyTls: true,
  extra: '',
  ub: emptyUb(),
};
export const EMPTY_SRV = { on: true, name: '', location: '', capacity: '500' };
export const KNOWN: Rec = {
  sanaei: ['inbound_ids', 'inbound_id', 'sub_base_url', 'api_style', 'verify_tls'],
  pasarguard: ['group_ids', 'user_template_id', 'verify_tls'],
  upstream_bot: UB_KEYS,
  mock: [],
};
export const ints = (a: Json) => (Array.isArray(a) ? a : []).map(Number).filter((n) => Number.isInteger(n) && n > 0);

// Rebuild the form from a stored panel; config keys the form has no field for stay in the JSON box so a save never drops them.
export function fromPanel(p: Json) {
  const c = p.config || {},
    f: Rec = { ...EMPTY, kind: p.kind, name: p.name, url: p.base_url, verifyTls: c.verify_tls !== false };
  if (p.kind === 'sanaei') {
    f.inbounds = ints(c.inbound_ids ?? (c.inbound_id != null ? [c.inbound_id] : []));
    f.subUrl = c.sub_base_url || '';
    f.apiStyle = c.api_style || 'auto';
  }
  if (p.kind === 'pasarguard') {
    if (c.user_template_id != null) {
      f.scope = 'template';
      f.tpl = String(c.user_template_id);
    } else f.groups = ints(c.group_ids);
  }
  if (p.kind === 'upstream_bot') f.ub = ubFromPanel(p);
  const rest = Object.fromEntries(Object.entries(c).filter(([k]) => !(KNOWN[p.kind] || []).includes(k)));
  f.extra = Object.keys(rest).length ? JSON.stringify(rest, null, 2) : '';
  return f;
}
export const parseExtra = (t: Json) => {
  if (!t.trim()) return {};
  const x = JSON.parse(t);
  if (!x || typeof x !== 'object' || Array.isArray(x)) throw new Error('obj');
  return x;
};

export function buildPayload(f: Json, withCreds: Json) {
  if (f.kind === 'upstream_bot')
    return {
      name: f.name.trim(),
      kind: f.kind,
      base_url: botUrl(ubBot(f.ub)),
      credentials: withCreds ? ubCredentials(f.ub) : {},
      config: { ...ubBuildConfig(f.ub), ...parseExtra(f.extra) },
    };
  const credentials: Rec = {};
  let config: Rec = {};
  if (withCreds && f.kind !== 'mock') {
    if (f.auth === 'token') credentials[f.kind === 'sanaei' ? 'api_token' : 'api_key'] = f.token.trim();
    else {
      credentials.username = f.user.trim();
      credentials.password = f.pass;
    }
  }
  if (f.kind === 'sanaei') config = { inbound_ids: f.inbounds, sub_base_url: f.subUrl.trim(), api_style: f.apiStyle };
  else if (f.kind === 'pasarguard') {
    if (f.scope === 'groups') config.group_ids = f.groups;
    else config.user_template_id = parseInt(f.tpl, 10);
  }
  if (f.kind !== 'mock') config.verify_tls = f.verifyTls;
  config = { ...config, ...parseExtra(f.extra) };
  if (f.kind === 'sanaei' && !config.inbound_ids?.length) delete config.inbound_ids;
  return { name: f.name.trim(), kind: f.kind, base_url: f.url.trim().replace(/\/+$/, ''), credentials, config };
}
export function validate(f: Json, withCreds: Json, srv: Json, edit: Json) {
  const e: Rec = {};
  let extra: Rec = {};
  if (f.extra.trim()) {
    try {
      extra = parseExtra(f.extra);
    } catch {
      e.extra = 'JSON پیشرفته نامعتبر است (باید یک شیء باشد)';
    }
  }
  if (!f.name.trim()) e.name = 'نام پنل را وارد کنید';
  if (f.kind === 'upstream_bot') Object.assign(e, ubValidate(f.ub, withCreds));
  else {
    try {
      const u = new URL(f.url.trim());
      if (!/^https?:$/.test(u.protocol)) throw 0;
    } catch {
      e.url = 'آدرس معتبر نیست (مثال: https://panel.example.com:2053/path)';
    }
  }
  if (
    withCreds &&
    f.kind !== 'mock' &&
    f.kind !== 'upstream_bot' &&
    (f.auth === 'token' ? !f.token.trim() : !(f.user.trim() && f.pass))
  )
    e.auth = f.auth === 'token' ? 'توکن را وارد کنید' : 'نام کاربری و رمز عبور هر دو لازم است';
  if (f.kind === 'sanaei') {
    if (!/^https?:\/\//.test(f.subUrl.trim()))
      e.subUrl = 'آدرس ساب‌اسکریپشن لازم است (مثال: https://sub.example.com:2096/sub)';
    if (!f.inbounds.length && !extra.template_username) e.inbounds = 'حداقل یک Inbound ID لازم است';
  }
  if (f.kind === 'pasarguard') {
    if (f.scope === 'groups' && !f.groups.length) e.scope = 'حداقل یک Group ID لازم است';
    if (f.scope === 'template' && !(parseInt(f.tpl, 10) > 0)) e.scope = 'شناسه قالب باید عدد مثبت باشد';
  }
  if (!edit && srv.on && !(Number(srv.capacity) >= 1 && Number(srv.capacity) <= 100000))
    e.capacity = 'ظرفیت باید بین ۱ تا ۱۰۰٬۰۰۰ باشد';
  return e;
}
