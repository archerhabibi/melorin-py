import { act } from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  Badge,
  DialogHost,
  ThemeButton,
  confirmDialog,
  dt,
  isStatus,
  label,
  noticeDialog,
  promptDialog,
  sid,
  tone,
} from '../src/ui.jsx';
import { getTheme } from '../src/theme.js';

describe('status helpers', () => {
  it('maps known statuses to a Persian label and tone class, unknown ones to a muted raw value', () => {
    render(
      <>
        <Badge s="completed" />
        <Badge s="failed" />
        <Badge s="processing" />
        <Badge s="mystery" />
        <Badge />
      </>,
    );
    expect(screen.getByText('تکمیل‌شده')).toHaveClass('b-ok');
    expect(screen.getByText('ناموفق')).toHaveClass('b-bd');
    expect(screen.getByText('در حال پردازش')).toHaveClass('b-in');
    expect(screen.getByText('mystery')).toHaveClass('b-mu');
    expect(screen.getByText('-')).toHaveClass('b-mu');
  });

  it('isStatus, tone and label agree with the table', () => {
    expect(isStatus('paid')).toBe(true);
    expect(isStatus('nope')).toBe(false);
    expect(isStatus(5)).toBe(false);
    expect(tone('paid')).toBe('ok');
    expect(tone('nope')).toBe('mu');
    expect(label('paid')).toBe('پرداخت‌شده');
    expect(label('nope')).toBe('nope');
  });

  it('dt and sid are safe on empty values', () => {
    expect(dt(null)).toBe('-');
    expect(dt('2026-10-22T10:30:00Z')).toMatch(/[۰-۹]/);
    expect(sid(undefined)).toBe('-');
    expect(sid('0123456789abcdef')).toBe('01234567');
  });
});

describe('ThemeButton', () => {
  it('toggles the theme on <html> in memory only', async () => {
    const user = userEvent.setup();
    render(<ThemeButton />);
    const before = getTheme();
    await user.click(screen.getByRole('button', { name: 'تغییر پوسته' }));
    expect(getTheme()).not.toBe(before);
    expect(document.documentElement.dataset.theme).toBe(getTheme());
    expect(window.localStorage.length).toBe(0); // policy: the admin panel never uses browser storage
    await user.click(screen.getByRole('button', { name: 'تغییر پوسته' }));
    expect(getTheme()).toBe(before);
    expect(document.documentElement.dataset.theme).toBe(before);
  });
});

describe('promise dialogs', () => {
  it('resolve to the safe default when no DialogHost is mounted', async () => {
    await expect(confirmDialog('x')).resolves.toBe(false);
    await expect(promptDialog('x')).resolves.toBeNull();
    await expect(noticeDialog('x')).resolves.toBeUndefined();
  });

  it('confirmDialog resolves true on confirm and false on cancel or Escape', async () => {
    const user = userEvent.setup();
    render(<DialogHost />);
    let p;
    act(() => {
      p = confirmDialog('حذف شود؟', { title: 'تأیید', danger: true, ok: 'حذف' });
    });
    expect(screen.getByRole('dialog', { name: 'تأیید' })).toBeInTheDocument();
    expect(screen.getByText('حذف شود؟')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'حذف' }));
    await expect(p).resolves.toBe(true);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    act(() => {
      p = confirmDialog('دوباره؟');
    });
    await user.click(screen.getByRole('button', { name: 'انصراف' }));
    await expect(p).resolves.toBe(false);

    act(() => {
      p = confirmDialog('باز هم؟');
    });
    await user.keyboard('{Escape}');
    await expect(p).resolves.toBe(false);
  });

  it('a backdrop click cancels but a click inside the card does not', async () => {
    const user = userEvent.setup();
    render(<DialogHost />);
    let p;
    act(() => {
      p = confirmDialog('x');
    });
    await user.click(screen.getByRole('dialog'));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    await user.click(screen.getByRole('dialog').parentElement);
    await expect(p).resolves.toBe(false);
  });

  it('promptDialog returns the typed text on OK/Enter and null when cancelled', async () => {
    const user = userEvent.setup();
    render(<DialogHost />);
    let p;
    act(() => {
      p = promptDialog('دلیل؟');
    });
    await user.type(screen.getByPlaceholderText(/دلیل یا توضیح/), 'تست');
    await user.click(screen.getByRole('button', { name: 'ثبت' }));
    await expect(p).resolves.toBe('تست');

    act(() => {
      p = promptDialog('دلیل؟');
    });
    await user.type(screen.getByPlaceholderText(/دلیل یا توضیح/), 'با اینتر{Enter}');
    await expect(p).resolves.toBe('با اینتر');

    act(() => {
      p = promptDialog('دلیل؟');
    });
    await user.click(screen.getByRole('button', { name: 'انصراف' }));
    await expect(p).resolves.toBeNull();
  });

  it('noticeDialog has a single button and resolves when dismissed', async () => {
    const user = userEvent.setup();
    render(<DialogHost />);
    let p;
    act(() => {
      p = noticeDialog('این مورد سابقه دارد', { title: 'حذف ممکن نیست' });
    });
    expect(screen.queryByRole('button', { name: 'انصراف' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'متوجه شدم' }));
    await expect(p).resolves.toBeUndefined();
  });

  it('unmounting the host makes later dialogs fall back to the safe default again', async () => {
    const { unmount } = render(<DialogHost />);
    unmount();
    await expect(confirmDialog('x')).resolves.toBe(false);
  });
});
