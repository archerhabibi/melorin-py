import { describe, expect, it } from 'vitest';
import { digits, errText, toEn } from '@melorin/web-kit/format.js';
import { formFromSource, sourceBody, toInt } from '@melorin/web-kit/bankSms.js';

describe('web-kit shared helpers', () => {
  it('normalises Persian and Arabic digits', () => {
    expect(toEn('۱۲۳٤٥')).toBe('12345');
    expect(digits('۱۲ ab ۳')).toBe('123');
    expect(toInt('')).toBeNull();
    expect(toInt('۱۵')).toBe(15);
  });
  it('reads the Core error message shapes', async () => {
    const r = (b) => ({ json: async () => b });
    expect(await errText(r({ error: { message: 'x' } }), 'f')).toBe('x');
    expect(await errText(r({ detail: 'y' }), 'f')).toBe('y');
    expect(await errText(r({ detail: [{ msg: 'Value error, z' }] }), 'f')).toBe('z');
    expect(
      await errText(
        {
          json: async () => {
            throw new Error('no');
          },
        },
        'f',
      ),
    ).toBe('f');
  });
  it('round-trips the bank SMS source form', () => {
    const form = formFromSource({
      configured: true,
      is_enabled: true,
      auto_verify: true,
      senders: ['A', 'B'],
      settings: {
        window_minutes: 30,
        time_tolerance_minutes: 5,
        require_claimed_time: true,
        max_auto_amount_rial: 0,
        account_number: '1 2 3',
      },
    });
    const body = sourceBody(form);
    expect(body.senders).toEqual(['A', 'B']);
    expect(body.settings).toMatchObject({ window_minutes: 30, max_auto_amount_rial: null, account_number: '123' });
  });
});
