import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ChannelJoinView from '../src/features/settings/ChannelJoinView.tsx';
import {
  channelProblem,
  draftProblem,
  fromConfig,
  joinUrl,
  move,
  parseChat,
  toPayload,
} from '../src/features/settings/channelJoin.ts';
import { DialogHost } from '../src/shared/ui.tsx';

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
const DEFAULT = 'برای استفاده از ربات، ابتدا در کانال‌های زیر عضو شوید و سپس روی «✅ عضو شدم» بزنید.';
const view = (config) => ({
  config: { enabled: false, channels: [], message: DEFAULT, cache_seconds: 300, ...config },
  defaults: { message: DEFAULT, cache_seconds: 300 },
  limits: { max_channels: 5, max_message: 1000, max_cache_seconds: 3600 },
});
const canon = (ch) => {
  const chat = parseChat(ch.chat);
  return { chat, title: ch.title || chat, url: ch.url || `https://t.me/${chat.slice(1)}` };
};

function setup(initial = {}, { check } = {}) {
  const calls = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (req, init = {}) => {
    const url = typeof req === 'string' ? req : req.url;
    const method = init.method || (typeof req === 'string' ? 'GET' : req.method);
    const body = init.body ?? (typeof req === 'string' ? undefined : await req.clone().text());
    const path = String(url).replace(/^https?:\/\/[^/]+/, '');
    calls.push([method, path, body]);
    if (path.endsWith('/check')) {
      const sent = JSON.parse(body);
      return check
        ? check(sent)
        : json({
            bot_username: 'melorin_bot',
            ok: true,
            channels: sent.channels.map((c) => ({ ...canon(c), ok: true })),
          });
    }
    if (method === 'PUT') {
      const sent = JSON.parse(body);
      return json(view({ ...sent, message: sent.message || DEFAULT, channels: sent.channels.map(canon) }));
    }
    return json(view(initial));
  });
  const toast = vi.fn();
  render(
    <>
      <ChannelJoinView api={{ base: 'http://core.test' }} toast={toast} />
      <DialogHost />
    </>,
  );
  return { calls, toast };
}

afterEach(() => vi.restoreAllMocks());

describe('channel join logic', () => {
  it('canonicalises the forms an admin types', () => {
    expect(parseChat('melorin_news')).toBe('@melorin_news');
    expect(parseChat('https://t.me/melorin_news/')).toBe('@melorin_news');
    expect(parseChat('-۱۰۰۱۲۳۴۵۶۷۸۹۰')).toBe('-1001234567890');
    expect(parseChat('https://t.me/+AbCdEfGh123')).toBeNull();
    expect(parseChat('@abc')).toBeNull();
  });
  it('requires an invite link for a private channel and only t.me links', () => {
    expect(channelProblem({ chat: '-1001234567890', title: '', url: '' })).toMatch(/لینک دعوت/);
    expect(channelProblem({ chat: '-1001234567890', title: '', url: 'https://t.me/+AbCdEfGh123' })).toBe('');
    expect(channelProblem({ chat: '@melorin_news', title: '', url: 'https://evil.example' })).toMatch(/t\.me/);
    expect(channelProblem({ chat: 't.me/+AbCdEfGh123', title: '', url: '' })).toMatch(/شناسهٔ عددی/);
    expect(joinUrl({ chat: '@melorin_news', title: '', url: '' })).toBe('https://t.me/melorin_news');
  });
  it('validates the whole draft like the server', () => {
    const d = { enabled: true, channels: [], message: '', cache_seconds: 300 };
    expect(draftProblem(d)).toMatch(/دست‌کم/);
    const dup = { chat: '@melorin_news', title: '', url: '' };
    expect(draftProblem({ ...d, channels: [dup, { ...dup, chat: 'Melorin_News' }] })).toMatch(/دو بار/);
    expect(draftProblem({ ...d, channels: [dup], cache_seconds: 9999 })).toMatch(/ثانیه/);
    expect(draftProblem({ ...d, channels: [dup] })).toBe('');
  });
  it('round-trips the payload and hides a default title', () => {
    const d = fromConfig({
      enabled: true,
      channels: [{ chat: '@a_news', title: '@a_news', url: 'https://t.me/a_news' }],
      message: 'm',
      cache_seconds: 60,
    });
    expect(d.channels[0].title).toBe('');
    expect(toPayload(d).channels[0]).toEqual({ chat: '@a_news', title: null, url: 'https://t.me/a_news' });
    expect(move([1, 2, 3], 0, 1)).toEqual([2, 1, 3]);
    expect(move([1, 2, 3], 0, -1)).toEqual([1, 2, 3]);
  });
});

describe('admin channel join (عضویت اجباری کانال)', () => {
  it('adds a channel, previews the join screen, checks with Telegram and saves', async () => {
    const { calls, toast } = setup();
    const user = userEvent.setup();
    await screen.findByText('عضویت اجباری در کانال');
    const save = screen.getByRole('button', { name: /ذخیره/ });
    expect(save).toBeDisabled();

    await user.click(screen.getByRole('switch', { name: 'فعال‌سازی عضویت اجباری' }));
    expect(screen.getByText(/دست‌کم یک کانال/)).toBeInTheDocument();
    expect(save).toBeDisabled();

    await user.click(screen.getByRole('button', { name: /افزودن کانال/ }));
    await user.type(screen.getByPlaceholderText('@my_channel'), 'melorin_news');
    await user.type(screen.getByLabelText(/عنوان دکمه/), 'اخبار ملورین');
    expect(screen.getByLabelText('پیش‌نمایش پیام ربات')).toHaveTextContent('📢 اخبار ملورین');
    expect(save).toBeEnabled();

    await user.click(save); // enabling runs the Telegram check first; all ok -> saved without a question
    await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.stringMatching(/اعمال می‌شود/)));
    const methods = calls.map(([m, p]) => `${m} ${p}`);
    expect(methods).toContain('POST /api/v1/admin/telegram/channel-join/check');
    const put = calls.find(([m]) => m === 'PUT');
    expect(JSON.parse(put[2])).toEqual({
      enabled: true,
      channels: [{ chat: 'melorin_news', title: 'اخبار ملورین', url: null }],
      message: DEFAULT,
      cache_seconds: 300,
    });
    expect(screen.getByText(/همهٔ کانال‌ها آماده‌اند/)).toBeInTheDocument();
  });

  it('asks before saving when the bot is not an admin of a channel, and shows the reason', async () => {
    const check = (sent) =>
      json({
        bot_username: 'melorin_bot',
        ok: false,
        channels: sent.channels.map((c) => ({ ...canon(c), ok: false, problem: 'ربات باید ادمین کانال باشد.' })),
      });
    const { calls } = setup(
      { channels: [{ chat: '@melorin_news', title: '@melorin_news', url: 'https://t.me/melorin_news' }] },
      { check },
    );
    const user = userEvent.setup();
    await screen.findByText('عضویت اجباری در کانال');
    await user.click(screen.getByRole('switch', { name: 'فعال‌سازی عضویت اجباری' }));
    await user.click(screen.getByRole('button', { name: /ذخیره/ }));
    expect(await screen.findByText(/در 1 کانال آماده نیست/)).toBeInTheDocument();
    expect(screen.getByText('ربات باید ادمین کانال باشد.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'انصراف' }));
    expect(calls.some(([m]) => m === 'PUT')).toBe(false);
  });

  it('shows the server refusal instead of a generic error', async () => {
    setup();
    vi.mocked(globalThis.fetch).mockImplementationOnce(async () =>
      json({ error: { code: 'MAIN_BOT_TOKEN_MISSING', message: 'توکن ربات اصلی تنظیم نشده است.' } }, 409),
    );
    const user = userEvent.setup();
    await screen.findByText('عضویت اجباری در کانال');
    await user.click(screen.getByRole('button', { name: /افزودن کانال/ }));
    await user.type(screen.getByPlaceholderText('@my_channel'), '@melorin_news');
    vi.mocked(globalThis.fetch).mockImplementationOnce(async () =>
      json({ error: { code: 'MAIN_BOT_TOKEN_MISSING', message: 'توکن ربات اصلی تنظیم نشده است.' } }, 409),
    );
    await user.click(screen.getByRole('button', { name: /بررسی کانال‌ها/ }));
    expect(await screen.findByText('توکن ربات اصلی تنظیم نشده است.')).toBeInTheDocument();
  });
});
