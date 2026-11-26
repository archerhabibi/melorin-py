// Pure logic of the mandatory channel membership editor (no React): Core payload types (from the OpenAPI snapshot), the
// per-channel problem check that mirrors melorin.domain.channel_join (the server stays the authority) and payload helpers.
import type { components } from '@melorin/api-client';

export type ChannelJoinView = components['schemas']['ChannelJoinView'];
export type ChannelJoinConfig = ChannelJoinView['config'];
export type ChannelJoinCheck = components['schemas']['ChannelJoinCheck'];
export type ChannelCheck = ChannelJoinCheck['channels'][number];
export type ChannelJoinIn = components['schemas']['ChannelJoinIn'];

/** One editable row. `chat` is what the admin typed (the server canonicalises it to `@name` or `-100…`). */
export interface ChannelDraft {
  chat: string;
  title: string;
  url: string;
}

export interface Draft {
  enabled: boolean;
  channels: ChannelDraft[];
  message: string;
  cache_seconds: number;
}

export const DEFAULT_LIMITS: ChannelJoinView['limits'] = {
  max_channels: 5,
  max_message: 1000,
  max_cache_seconds: 3600,
};

const DIGITS = '۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩';
const latinDigits = (s: string) => s.replace(/[۰-۹٠-٩]/g, (d) => String(DIGITS.indexOf(d) % 10));
const USERNAME = /^[A-Za-z][A-Za-z0-9_]{3,30}[A-Za-z0-9]$/;
const CHAT_ID = /^-100[0-9]{5,16}$/;
const LINK = /^(?:https?:\/\/)?(?:www\.)?(?:t|telegram)\.me\/([^?#\s]+?)\/?(?:[?#].*)?$/i;
const INVITE = /^(?:https?:\/\/)?(?:t|telegram)\.me\/(?:\+|joinchat\/)[A-Za-z0-9_-]{8,64}$/i;
const PUBLIC_URL = /^(?:https?:\/\/)?(?:t|telegram)\.me\/[A-Za-z][A-Za-z0-9_]{3,30}[A-Za-z0-9]$/i;

/** `@name` / `name` / `t.me/name` -> `@name`; `-100…` stays; null when it cannot identify a channel. */
export function parseChat(raw: string): string | null {
  let text = latinDigits(raw.trim());
  if (!text) return null;
  if (CHAT_ID.test(text)) return text;
  const m = LINK.exec(text);
  if (m) {
    if (m[1].startsWith('+') || m[1].toLowerCase().startsWith('joinchat/')) return null; // an invite link is not an id
    text = m[1].split('/')[0];
  }
  const name = text.replace(/^@/, '');
  return USERNAME.test(name) ? `@${name}` : null;
}

export const isPrivate = (ch: ChannelDraft): boolean => parseChat(ch.chat)?.startsWith('-100') ?? false;

/** The link users tap: the admin's one, or `https://t.me/<username>` for a public channel. */
export function joinUrl(ch: ChannelDraft): string {
  if (ch.url.trim()) return ch.url.trim();
  const chat = parseChat(ch.chat);
  return chat?.startsWith('@') ? `https://t.me/${chat.slice(1)}` : '';
}

/** First problem of one row, in Persian, or '' when the server is expected to accept it. */
export function channelProblem(ch: ChannelDraft): string {
  const raw = ch.chat.trim();
  if (!raw) return 'شناسهٔ کانال را وارد کنید.';
  if (INVITE.test(raw))
    return 'لینک دعوت شناسهٔ کانال نیست؛ شناسهٔ عددی (‎-100…‎) را بگذارید و لینک را در «لینک عضویت».';
  const chat = parseChat(raw);
  if (!chat) return '‎@username‎ کانال عمومی یا شناسهٔ عددی ‎-100…‎ کانال خصوصی را وارد کنید.';
  const url = ch.url.trim();
  if (!url) return chat.startsWith('-100') ? 'کانال خصوصی لینک دعوت لازم دارد (‎https://t.me/+…‎).' : '';
  return INVITE.test(url) || PUBLIC_URL.test(url) ? '' : 'لینک عضویت باید یک لینک ‎t.me‎ باشد.';
}

export function draftProblem(d: Draft, limits = DEFAULT_LIMITS): string {
  if (d.enabled && d.channels.length === 0) return 'برای فعال‌سازی دست‌کم یک کانال اضافه کنید.';
  if (d.channels.length > limits.max_channels) return `حداکثر ${limits.max_channels} کانال مجاز است.`;
  const seen = new Set<string>();
  for (const ch of d.channels) {
    const p = channelProblem(ch);
    if (p) return p;
    const key = (parseChat(ch.chat) ?? '').toLowerCase();
    if (seen.has(key)) return `کانال ${parseChat(ch.chat)} دو بار آمده است.`;
    seen.add(key);
  }
  if (d.message.length > limits.max_message) return `متن پیام حداکثر ${limits.max_message} نویسه است.`;
  if (!Number.isInteger(d.cache_seconds) || d.cache_seconds < 0 || d.cache_seconds > limits.max_cache_seconds)
    return `مدت به‌خاطرسپاری باید بین ۰ و ${limits.max_cache_seconds} ثانیه باشد.`;
  return '';
}

export const fromConfig = (c: ChannelJoinConfig): Draft => ({
  enabled: c.enabled,
  channels: c.channels.map((ch) => ({ chat: ch.chat, title: ch.title === ch.chat ? '' : ch.title, url: ch.url })),
  message: c.message,
  cache_seconds: c.cache_seconds,
});

export const toPayload = (d: Draft): ChannelJoinIn => ({
  enabled: d.enabled,
  channels: d.channels.map((ch) => ({
    chat: ch.chat.trim(),
    title: ch.title.trim() || null,
    url: ch.url.trim() || null,
  })),
  message: d.message.trim() || null,
  cache_seconds: d.cache_seconds,
});

export const sameDraft = (a: Draft, b: Draft): boolean => JSON.stringify(toPayload(a)) === JSON.stringify(toPayload(b));

export const blankChannel = (): ChannelDraft => ({ chat: '', title: '', url: '' });

export function move<T>(list: T[], from: number, to: number): T[] {
  if (to < 0 || to >= list.length) return list;
  const next = [...list];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}
