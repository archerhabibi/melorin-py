import { describe, expect, it } from 'vitest';
import {
  UB_NUM,
  UB_TEXT,
  botUrl,
  emptyUb,
  parseBot,
  ubBuildConfig,
  ubCredentials,
  ubFlows,
  ubFromPanel,
  ubSummary,
  ubValidate,
} from '../src/upstreamBot.js';

const SESSION = '1' + 'A'.repeat(120);
const ok = (over = {}) => ({ ...emptyUb(), bot: 'parent_bot', maxPrice: '100000', ...over });

describe('parseBot', () => {
  it.each([
    ['@parent_bot', 'parent_bot'],
    ['parent_bot', 'parent_bot'],
    ['t.me/parent_bot', 'parent_bot'],
    ['https://t.me/parent_bot/', 'parent_bot'],
    ['https://t.me/parent_bot?start=x', 'parent_bot'],
    ['http://telegram.me/Parent_Bot', 'Parent_Bot'],
    ['  @parent_bot  ', 'parent_bot'],
  ])('%s -> %s', (raw, bot) => expect(parseBot(raw)).toBe(bot));
  it.each(['', 'https://example.com/parent_bot', 'two words', 'https://t.me/+invite/abc'])('rejects %j', (raw) =>
    expect(parseBot(raw)).toBe(''),
  );
  it('builds the canonical url the adapter parses', () => expect(botUrl('parent_bot')).toBe('https://t.me/parent_bot'));
});

describe('config round trip', () => {
  it('stores only real overrides and keeps renew.enabled explicit', () => {
    expect(ubBuildConfig(ok())).toEqual({ max_price: 100000, renew: { enabled: true } });
    const cfg = ubBuildConfig(
      ok({
        t: { service_button: 'سرویس ویژه', menu_buy: UB_TEXT.menu_buy, link_button: '  ' },
        n: { status_ttl: '120', step_timeout: String(UB_NUM.step_timeout) },
        renewOn: false,
        r: { renew_button: 'تمدید', settle_window: '900' },
        rWords: ['انجام شد', ' '],
      }),
    );
    expect(cfg).toEqual({
      max_price: 100000,
      service_button: 'سرویس ویژه',
      status_ttl: 120,
      renew: { enabled: false, renew_button: 'تمدید', settle_window: 900, success_words: ['انجام شد'] },
    });
  });

  it('accepts Persian digits and builds plans', () => {
    const cfg = ubBuildConfig(
      ok({ maxPrice: '۱۵۰۰۰۰', plans: [{ traffic_gb: '۱۰', months: '۱', label: '10 گیگ یک ماهه' }] }),
    );
    expect(cfg.max_price).toBe(150000);
    expect(cfg.plans).toEqual([{ traffic_gb: 10, months: 1, label: '10 گیگ یک ماهه' }]);
  });

  it('loads a stored panel and saves it back without losing unknown renew keys', () => {
    const panel = {
      base_url: 'https://t.me/parent_bot',
      config: {
        max_price: 90000,
        service_button: 'سرویس ویژه',
        status_ttl: 60,
        poll_interval: 2,
        plans: [{ traffic_gb: 10, months: 1, label: 'x' }],
        renew: { enabled: false, future_flag: 7, settle_window: 300 },
      },
    };
    const ub = ubFromPanel(panel);
    expect(ub).toMatchObject({ bot: 'parent_bot', maxPrice: '90000', renewOn: false });
    expect(ub.t).toEqual({ service_button: 'سرویس ویژه' });
    expect(ub.n).toEqual({}); // equals the default -> not an override
    const cfg = ubBuildConfig(ub);
    expect(cfg.renew).toEqual({ future_flag: 7, enabled: false, settle_window: 300 });
    expect(cfg.max_price).toBe(90000);
    expect('poll_interval' in cfg).toBe(false); // owned by the advanced JSON box, merged by the caller
  });

  it('treats a renew block without `enabled` as enabled (adapter default)', () => {
    expect(ubFromPanel({ base_url: 'https://t.me/parent_bot', config: { max_price: 1, renew: {} } }).renewOn).toBe(
      true,
    );
  });

  it('normalises credentials', () => {
    expect(ubCredentials(ok({ apiId: '۱۲۳۴۵۶', apiHash: ' abc ', session: 'AA\nBB ' }))).toEqual({
      api_id: 123456,
      api_hash: 'abc',
      session: 'AABB',
    });
  });
});

describe('ubValidate', () => {
  const creds = { apiId: '123456', apiHash: 'a'.repeat(32), session: SESSION };
  it('passes a complete form', () => expect(ubValidate(ok(creds), true)).toEqual({}));
  it('does not ask for credentials when they are kept', () => expect(ubValidate(ok(), false)).toEqual({}));
  it('requires the safety cap, the bot and valid credentials', () => {
    const e = ubValidate(emptyUb(), true);
    expect(Object.keys(e).sort()).toEqual(['apiHash', 'apiId', 'bot', 'maxPrice', 'session']);
    expect(ubValidate(ok({ ...creds, maxPrice: '0' }), true).maxPrice).toBeTruthy();
    expect(ubValidate(ok({ ...creds, apiHash: 'xyz' }), true).apiHash).toBeTruthy();
    expect(ubValidate(ok({ ...creds, session: 'short' }), true).session).toBeTruthy();
    expect(ubValidate(ok({ bot: 'abc' }), false).bot).toBeTruthy();
  });
  it('validates numbers, start command and plans', () => {
    const e = ubValidate(
      ok({
        n: { status_ttl: '0', delivery_timeout: '5000' },
        t: { start_command: 'start' },
        plans: [{ traffic_gb: '0', months: '1', label: '' }],
      }),
      false,
    );
    expect(Object.keys(e).sort()).toEqual(['delivery_timeout', 'plans', 'start_command', 'status_ttl']);
  });
  it('ignores renew settings while renewal is off', () => {
    expect(ubValidate(ok({ renewOn: false, r: { settle_window: '0' } }), false)).toEqual({});
    expect(ubValidate(ok({ renewOn: true, r: { settle_window: '0' } }), false).settle_window).toBeTruthy();
  });
});

describe('flows and summary', () => {
  it('uses the configured button texts and marks renewal off', () => {
    const f = ubFlows(ok({ t: { menu_buy: 'خرید جدید' }, renewOn: false, r: { renew_button: 'تمدید سریع' } }));
    expect(f.map((x) => x.id)).toEqual(['buy', 'status', 'refund', 'renew']);
    expect(f[0].steps.map((s) => s.l)).toContain('خرید جدید');
    expect(f[3].off).toBe(true);
    expect(f[3].steps.map((s) => s.l)).toContain('تمدید سریع');
  });
  it('summarises a stored panel for the card header', () => {
    expect(
      ubSummary({
        base_url: 'https://t.me/parent_bot',
        config: { max_price: 100000, renew: { enabled: false }, plans: [{}] },
      }),
    ).toEqual({
      bot: 'parent_bot',
      maxPrice: 100000,
      renewOn: false,
      plans: 1,
    });
  });
});
