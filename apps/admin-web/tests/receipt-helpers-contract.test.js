import { describe, expect, it } from 'vitest';
import { errorMessage } from '../src/api/api.ts';
import { parseStoreBase } from '../src/features/payments/receiptHelpers.ts';
import { duplicateLine } from '../src/features/payments/ReceiptDuplicatePolicy.tsx';

describe('parseStoreBase', () => {
  it('reads the admin and the reseller family strictly', () => {
    expect(parseStoreBase('/api/v1/admin/stores/s1')).toEqual({ scope: 'admin', storeId: 's1' });
    expect(parseStoreBase('/api/v1/admin/stores/s1/')).toEqual({ scope: 'admin', storeId: 's1' });
    expect(parseStoreBase('/api/v1/stores/s2/reseller')).toEqual({ scope: 'reseller', storeId: 's2' });
  });
  it('never guesses: anything else is null', () => {
    for (const bad of [
      undefined,
      null,
      '',
      '/api/v1/admin/stores/',
      '/api/v1/admin/stores/s1/reseller',
      '/api/v1/stores/s1',
      '/x/stores/s1/reseller',
    ])
      expect(parseStoreBase(bad)).toBeNull();
  });
});

describe('errorMessage', () => {
  it('prefers the API envelope, then FastAPI detail, then the fallback', () => {
    expect(errorMessage({ error: { message: 'a' }, detail: 'b' }, 'f')).toBe('a');
    expect(errorMessage({ detail: 'b' }, 'f')).toBe('b');
    expect(errorMessage({ detail: [{ msg: 'Value error, c' }] }, 'f')).toBe('c');
    expect(errorMessage({ detail: { message: 'd' } }, 'f')).toBe('d');
    for (const none of [undefined, null, 'text', {}, { detail: [] }, { error: {} }])
      expect(errorMessage(none, 'f')).toBe('f');
  });
});

describe('duplicateLine', () => {
  it('names own-store payments (max three) and only counts other stores', () => {
    expect(duplicateLine(null)).toBe('');
    expect(duplicateLine({ payments: [] })).toBe('');
    const ids = ['aaaaaaaa1', 'bbbbbbbb2', 'cccccccc3', 'dddddddd4'].map((id) => ({ id }));
    expect(duplicateLine({ payments: ids, other_stores: 2 })).toBe(
      'همین تصویر قبلاً برای پرداخت aaaaaaaa، bbbbbbbb، cccccccc و 1 مورد دیگر و 2 پرداخت در فروشگاه دیگر ثبت شده است.',
    );
  });
});
