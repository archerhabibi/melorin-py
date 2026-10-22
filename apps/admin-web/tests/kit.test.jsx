import { act } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, renderHook, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChipList, capTone, digits, errText, num, removeEntity, tint, toEn, useRows } from '../src/kit.jsx';
import { DialogHost } from '../src/ui.jsx';

const res = (body, status = 200) => new Response(status === 204 ? null : JSON.stringify(body), { status });

describe('digit normalisation', () => {
  it('converts Persian and Arabic-Indic digits to ASCII', () => {
    expect(toEn('۱۲۳۴۵۶۷۸۹۰')).toBe('1234567890');
    expect(toEn('٠١٢٣٤٥٦٧٨٩')).toBe('0123456789');
    expect(toEn(null)).toBe('');
  });

  it('digits keeps digits only, whatever script they were typed in', () => {
    expect(digits('۱۲٬۵۰۰ تومان')).toBe('12500');
    expect(digits('abc')).toBe('');
  });

  it('num formats with Persian digits and treats empty as zero', () => {
    expect(num(1500)).toBe('۱٬۵۰۰');
    expect(num(undefined)).toBe('۰');
  });
});

describe('small helpers', () => {
  it('capTone: red at 100%+, amber from 80%, green below', () => {
    expect([capTone(0.2), capTone(0.79), capTone(0.8), capTone(0.99), capTone(1), capTone(1.4)]).toEqual([
      'ok',
      'ok',
      'wn',
      'wn',
      'bd',
      'bd',
    ]);
  });

  it('tint builds CSS variable fallbacks for a tone', () => {
    expect(tint('ok')).toEqual({ background: 'var(--okb, var(--mb))', color: 'var(--ok, var(--mu))' });
  });

  it('ChipList shows at most max chips plus a +n overflow marker', () => {
    render(<ChipList items={['a', 'b', 'c', 'd', 'e']} max={2} renderItem={(x) => <i key={x}>{x}</i>} />);
    expect(screen.getAllByText(/^[a-e]$/)).toHaveLength(2);
    expect(screen.getByText('+۳')).toBeInTheDocument();
  });

  it('ChipList shows no overflow marker when everything fits', () => {
    render(<ChipList items={['a']} renderItem={(x) => <i key={x}>{x}</i>} />);
    expect(screen.queryByText(/^\+/)).not.toBeInTheDocument();
  });
});

describe('errText', () => {
  it('prefers the Core error envelope message', async () => {
    expect(await errText(res({ error: { message: 'پیام' }, detail: 'x' }), 'fb')).toBe('پیام');
  });

  it.each([
    [{ detail: 'plain' }, 'plain'],
    [{ detail: { message: 'nested' } }, 'nested'],
    [{ detail: [{ msg: 'Value error, bad value' }] }, 'bad value'],
    [{}, 'fb'],
  ])('reads %j', async (body, expected) => {
    expect(await errText(res(body), 'fb')).toBe(expected);
  });

  it('falls back when the body is not JSON', async () => {
    expect(await errText(new Response('<html>', { status: 502 }), 'fb')).toBe('fb');
  });
});

describe('removeEntity', () => {
  const opts = (toast) => ({ title: 'حذف', message: 'مطمئنید؟', done: 'حذف شد', toast });

  async function run(call, toast, answer) {
    const user = userEvent.setup();
    render(<DialogHost />);
    let p;
    act(() => {
      p = removeEntity(call, '/items/1', opts(toast));
    });
    if (answer === 'cancel') await user.click(await screen.findByRole('button', { name: 'انصراف' }));
    else await user.click(await screen.findByRole('button', { name: 'حذف دائمی' }));
    return { p, user };
  }

  it('does nothing when the admin cancels the confirmation', async () => {
    const call = vi.fn();
    const toast = vi.fn();
    const { p } = await run(call, toast, 'cancel');
    await expect(p).resolves.toBe(false);
    expect(call).not.toHaveBeenCalled();
    expect(toast).not.toHaveBeenCalled();
  });

  it('DELETEs, reports success and resolves true', async () => {
    const call = vi.fn().mockResolvedValue(res({}, 204));
    const toast = vi.fn();
    const { p } = await run(call, toast, 'ok');
    await expect(p).resolves.toBe(true);
    expect(call).toHaveBeenCalledWith('/items/1', { method: 'DELETE' });
    expect(toast).toHaveBeenCalledWith('حذف شد');
  });

  it('shows the Core reason in a dialog on 409 (item has history) and resolves false', async () => {
    const call = vi.fn().mockResolvedValue(res({ error: { message: 'این محصول سفارش دارد.' } }, 409));
    const toast = vi.fn();
    const { p, user } = await run(call, toast, 'ok');
    expect(await screen.findByText('این محصول سفارش دارد.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'متوجه شدم' }));
    await expect(p).resolves.toBe(false);
    expect(toast).not.toHaveBeenCalled();
  });

  it('toasts other server errors and network failures instead of throwing', async () => {
    const toast = vi.fn();
    let out = await run(vi.fn().mockResolvedValue(res({ detail: 'نمی‌شود' }, 400)), toast, 'ok');
    await expect(out.p).resolves.toBe(false);
    expect(toast).toHaveBeenLastCalledWith('نمی‌شود');
    out = await run(vi.fn().mockRejectedValue(new TypeError('offline')), toast, 'ok');
    await expect(out.p).resolves.toBe(false);
    expect(toast).toHaveBeenLastCalledWith('ارتباط با سرور برقرار نشد');
  });
});

describe('useRows', () => {
  it('is null while loading, then the list (array or {items})', async () => {
    const call = vi.fn().mockResolvedValue(res({ items: [{ id: 1 }] }));
    const { result } = renderHook(() => useRows(call, '/x'));
    expect(result.current.rows).toBeNull();
    await waitFor(() => expect(result.current.rows).toEqual([{ id: 1 }]));
  });

  it('does not fetch when skipped and starts with an empty list', () => {
    const call = vi.fn();
    const { result } = renderHook(() => useRows(call, '/x', { skip: true }));
    expect(result.current.rows).toEqual([]);
    expect(call).not.toHaveBeenCalled();
  });
});
