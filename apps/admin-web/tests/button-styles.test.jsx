import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ButtonStylesView from '../src/ButtonStylesView.tsx';
import {
  blankRule,
  hasVisible,
  isEmojiId,
  renderInline,
  renderReply,
  ruleProblem,
  toPayload,
} from '../src/buttonStyles.ts';
import { DialogHost } from '../src/ui.tsx';

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });

const CATALOG = [
  { kind: 'inline', key: 'menu:plans', match: 'exact', label: '🛒 خرید اکانت', group: 'ناوبری' },
  { kind: 'inline', key: 'buy:', match: 'prefix', label: '✅ خرید / پرداخت', group: 'خرید و پرداخت' },
  { kind: 'reply', key: '🛒 خرید اکانت', match: 'exact', label: '🛒 خرید اکانت', group: 'منوی اصلی (کیبورد پایین)' },
];
const PRESETS = [
  {
    id: 'classic',
    name: 'رنگی کلاسیک',
    description: 'd',
    rules: [
      {
        kind: 'inline',
        match: 'prefix',
        key: 'buy:',
        style: 'success',
        prefix: '',
        suffix: '',
        icon: null,
        enabled: true,
      },
    ],
  },
];
const payload = (config) => ({
  config,
  catalog: CATALOG,
  presets: PRESETS,
  styles: [],
  limits: { max_rules: 120, max_decor: 6, url_key: '@url' },
});

function setup(initial = { enabled: false, rules: [] }, { put, preview } = {}) {
  const calls = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, o = {}) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '');
    calls.push([o.method || 'GET', path, o.body]);
    if (path.endsWith('/preview')) return preview ? preview() : json({ ok: true });
    if (o.method === 'PUT') return put ? put(o) : json(payload(JSON.parse(o.body)));
    return json(payload(initial));
  });
  const toast = vi.fn();
  render(
    <>
      <ButtonStylesView api={{ base: 'http://core.test' }} toast={toast} />
      <DialogHost />
    </>,
  );
  return { calls, toast };
}

describe('button style logic', () => {
  const cfg = (rules, enabled = true) => ({ enabled, rules });
  it('matches like the server: exact beats prefix, longer prefix beats shorter', () => {
    const c = cfg([
      blankRule({ key: 'menu:', match: 'prefix', style: 'primary' }),
      blankRule({ key: 'menu:wa', match: 'prefix', style: 'danger' }),
      blankRule({ key: 'menu:plans', style: 'success', prefix: '💎 ' }),
    ]);
    expect(renderInline(c, 'menu:plans', 'x')).toEqual({ text: '💎 x', style: 'success', icon: null });
    expect(renderInline(c, 'menu:wallet', 'x').style).toBe('danger');
    expect(renderInline(c, 'menu:orders', 'x').style).toBe('primary');
    expect(renderInline(c, 'zzz', 'x').style).toBeNull();
    expect(renderInline(cfg(c.rules, false), 'menu:plans', 'x').style).toBeNull();
  });
  it('never decorates the reply keyboard text', () => {
    const c = cfg([blankRule({ kind: 'reply', key: 'a', style: 'success', prefix: 'X' })]);
    expect(renderReply(c, 'a')).toEqual({ text: 'a', style: 'success', icon: null });
  });
  it('validates a rule and normalises Persian digits before sending', () => {
    expect(ruleProblem(blankRule({ key: 'k' }), 6)).toMatch(/حداقل/);
    expect(ruleProblem(blankRule({ key: 'k', style: 'primary', icon: 'abc' }), 6)).toMatch(/ایموجی/);
    expect(ruleProblem(blankRule({ key: 'k', style: 'primary', icon: '12345' }), 6)).toBe('');
    expect(toPayload(cfg([blankRule({ key: ' k ', icon: '۱۲۳۴۵۶' })])).rules[0]).toMatchObject({
      key: 'k',
      icon: '123456',
    });
  });
});

describe('admin button styles (دکمه‌های تلگرام)', () => {
  it('shows the live preview coloured from the draft and saves exactly what was edited', async () => {
    const { calls, toast } = setup();
    const user = userEvent.setup();
    await screen.findByText('رنگی‌سازی دکمه‌های تلگرام');
    const save = screen.getByRole('button', { name: /ذخیره/ });
    expect(save).toBeDisabled();

    await user.selectOptions(screen.getByRole('combobox'), 'inline|exact|menu:plans');
    await user.click(screen.getByRole('button', { name: /افزودن/ }));
    const card = screen.getByText('menu:plans', { selector: 'code' }).closest('li');
    await user.click(within(card).getByRole('radio', { name: 'سبز' }));
    await user.type(within(card).getByLabelText(/پیشوند/), '💎 ');
    await user.click(screen.getByRole('switch', { name: 'فعال‌سازی رنگی‌سازی دکمه‌ها' }));

    const preview = screen.getByLabelText('پیش‌نمایش دکمه‌ها');
    const buy = within(preview).getByText('💎 🛒 خرید اکانت').closest('.tg-btn');
    expect(buy).toHaveAttribute('data-style', 'success');
    expect(within(preview).getByText('💰 کیف پول').closest('.tg-btn')).toHaveAttribute('data-style', 'none');

    await user.click(screen.getByRole('button', { name: /ذخیره/ }));
    await waitFor(() => expect(toast).toHaveBeenCalled());
    const put = calls.find((c) => c[0] === 'PUT');
    expect(JSON.parse(put[2])).toMatchObject({
      enabled: true,
      rules: [{ key: 'menu:plans', style: 'success', prefix: '💎 ' }],
    });
  });

  it('blocks saving an invalid premium emoji id and shows why', async () => {
    setup({ enabled: true, rules: [blankRule({ key: 'menu:plans', style: 'success', icon: '123456' })] });
    const user = userEvent.setup();
    const input = await screen.findByPlaceholderText('5368324170671202286');
    await user.clear(input);
    await user.type(input, 'abc');
    expect(screen.getByText('شناسه معتبر نیست')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /ذخیره/ })).toBeDisabled();
  });

  it('applies a preset after confirmation and reports a Telegram refusal from the sample send', async () => {
    const { calls } = setup(
      { enabled: true, rules: [blankRule({ key: 'x:', match: 'prefix', style: 'danger' })] },
      {
        preview: () =>
          json({ error: { code: 'TELEGRAM_REJECTED_STYLE', message: 'تلگرام پیش‌نمایش را نپذیرفت' } }, 422),
      },
    );
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /رنگی کلاسیک/ }));
    await user.click(await screen.findByRole('button', { name: 'جایگزین کن' }));
    expect(await screen.findByText('✅ خرید / پرداخت')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /ارسال نمونه به تلگرام من/ }));
    expect(await screen.findByText(/تلگرام پیش‌نمایش را نپذیرفت/)).toBeInTheDocument();
    expect(calls.some((c) => c[1].endsWith('/preview'))).toBe(true);
  });
});

describe('rule validation mirrors the server (no round trip needed to learn a rule is refused)', () => {
  const rule = (over = {}) => blankRule({ key: 'menu:plans', style: 'primary', ...over });

  it('accepts a normal rule', () => {
    expect(ruleProblem(rule(), 6)).toBe('');
  });

  it.each([
    ['link used as a callback key', { key: 'https://x.example/a' }],
    ['@url with prefix match', { key: '@url', match: 'prefix' }],
    ['key with a line break', { key: 'menu:\nplans' }],
    ['inline key longer than 64', { key: 'a'.repeat(65) }],
    ['emoji id with a leading zero', { icon: '012345' }],
    ['emoji id longer than 19 digits', { icon: '1'.repeat(20) }],
    ['blank-only decoration and nothing else', { style: null, prefix: '   ' }],
  ])('flags %s', (_name, over) => {
    expect(ruleProblem(rule(over), 6)).not.toBe('');
  });

  it('allows a long reply-keyboard text up to 100 and ignores decoration for it', () => {
    expect(ruleProblem(rule({ kind: 'reply', key: 'x'.repeat(100) }), 6)).toBe('');
    expect(ruleProblem(rule({ kind: 'reply', key: 'x', style: null, prefix: '💎' }), 6)).not.toBe('');
  });

  it('sends blank decoration as empty and normalises Persian digits', () => {
    const { rules } = toPayload({
      enabled: true,
      rules: [rule({ prefix: '  ', suffix: ' ✨', icon: '۵۳۶۸۳۲۴۱۷۰۶۷۱۲۰۲۲۸۶' })],
    });
    expect(rules[0]).toMatchObject({ prefix: '', suffix: ' ✨', icon: '5368324170671202286' });
  });
});

describe('stricter mirror of the server rules (int64 emoji ids, invisible text)', () => {
  const rule = (over = {}) => blankRule({ key: 'menu:plans', style: 'primary', ...over });

  it('accepts the largest int64 id and refuses anything above it', () => {
    expect(isEmojiId('9223372036854775807')).toBe(true);
    expect(isEmojiId('9223372036854775808')).toBe(false);
    expect(isEmojiId('9999999999999999999')).toBe(false);
    expect(isEmojiId('5368324170671202286')).toBe(true);
    expect(isEmojiId('۵۳۶۸۳۲۴۱۷۰۶۷۱۲۰۲۲۸۶')).toBe(true);
    expect(ruleProblem(rule({ icon: '9999999999999999999' }), 6)).toMatch(/ایموجی/);
  });

  it('treats zero-width and bidi characters as invisible', () => {
    expect(hasVisible('\u200b')).toBe(false);
    expect(hasVisible(' \u200f ')).toBe(false);
    expect(hasVisible('💎 ')).toBe(true);
    expect(hasVisible('👨\u200d👩')).toBe(true);
  });

  it('flags an invisible key and an invisible-only decoration, like the server', () => {
    expect(ruleProblem(rule({ key: '\u200b' }), 6)).not.toBe('');
    expect(ruleProblem(rule({ style: null, prefix: '\u200f' }), 6)).toMatch(/حداقل/);
  });

  it('drops invisible decoration from the payload and from the preview', () => {
    const { rules } = toPayload({ enabled: true, rules: [rule({ prefix: '\u200b', suffix: '👨\u200d👩' })] });
    expect(rules[0]).toMatchObject({ prefix: '', suffix: '👨\u200d👩' });
    const cfg = { enabled: true, rules: [rule({ key: 'menu:', match: 'prefix', prefix: '\u200b' })] };
    expect(renderInline(cfg, 'menu:plans', 'خرید').text).toBe('خرید');
  });
});

describe('custom rules', () => {
  it('a custom @url rule starts as an exact rule, not as an invalid prefix rule', async () => {
    setup();
    const user = userEvent.setup();
    await screen.findByText('رنگی‌سازی دکمه‌های تلگرام');
    await user.click(screen.getByRole('button', { name: /قانون سفارشی/ }));
    await user.type(screen.getByPlaceholderText('menu:plans'), '@url');
    await user.click(screen.getByRole('button', { name: /افزودن/ }));
    const card = screen.getByText('@url', { selector: 'code' }).closest('li');
    expect(within(card).getByText('دقیق')).toBeInTheDocument();
    expect(within(card).queryByText(/فقط تطبیق دقیق/)).not.toBeInTheDocument();
  });
});
