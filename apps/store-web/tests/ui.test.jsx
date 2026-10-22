import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Empty, Loading, Modal, StatusBadge, ThemeToggle, fa, fd, initTheme } from '../src/ui.jsx';

describe('formatting helpers', () => {
  it('fa renders Persian digits with grouping and tolerates junk', () => {
    expect(fa(1234567)).toBe('۱٬۲۳۴٬۵۶۷');
    expect(fa('12')).toBe('۱۲');
    expect(fa(undefined)).toBe('۰');
    expect(fa('abc')).toBe('۰');
  });

  it('fd shows a dash for an empty date and a Persian date otherwise', () => {
    expect(fd(null)).toBe('—');
    expect(fd('2026-10-22T10:30:00Z')).toMatch(/[۰-۹]/);
  });
});

describe('StatusBadge', () => {
  it('shows the Persian label for known statuses, case-insensitively', () => {
    render(<StatusBadge status="Completed" />);
    expect(screen.getByText('تکمیل‌شده')).toBeInTheDocument();
  });

  it('falls back to the raw value (neutral) for unknown statuses and a dash for none', () => {
    const { rerender } = render(<StatusBadge status="weird_state" />);
    expect(screen.getByText('weird_state').closest('.badge')).toHaveClass('text-muted');
    rerender(<StatusBadge />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('marks failures with the danger tone', () => {
    render(<StatusBadge status="failed" />);
    expect(screen.getByText('ناموفق').closest('.badge')).toHaveClass('text-danger');
  });
});

describe('theme', () => {
  it('initTheme prefers the stored choice over the OS preference', () => {
    localStorage.setItem('melorin-theme', 'dark');
    vi.stubGlobal('matchMedia', () => ({ matches: false }));
    initTheme();
    expect(document.documentElement.dataset.theme).toBe('dark');
    localStorage.clear();
  });

  it('initTheme follows the OS preference when nothing is stored, and survives broken storage', () => {
    vi.stubGlobal('matchMedia', () => ({ matches: true }));
    initTheme();
    expect(document.documentElement.dataset.theme).toBe('dark');
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.stubGlobal('matchMedia', () => ({ matches: false }));
    expect(() => initTheme()).not.toThrow();
    expect(document.documentElement.dataset.theme).toBe('light');
  });

  it('ThemeToggle flips the theme, persists it and keeps working when storage throws', async () => {
    document.documentElement.dataset.theme = 'light';
    document.head.innerHTML = '<meta name="theme-color" content="#fff">';
    const user = userEvent.setup();
    render(<ThemeToggle />);
    await user.click(screen.getByRole('button', { name: 'تم تیره' }));
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(localStorage.getItem('melorin-theme')).toBe('dark');
    expect(document.querySelector('meta[name="theme-color"]')).toHaveAttribute('content', '#08111f');
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota');
    });
    await user.click(screen.getByRole('button', { name: 'تم روشن' }));
    expect(document.documentElement.dataset.theme).toBe('light');
    localStorage.clear();
  });
});

describe('Modal', () => {
  const open = (onClose = vi.fn()) => {
    render(
      <Modal onClose={onClose} title="عنوان">
        <input aria-label="field" />
      </Modal>,
    );
    return onClose;
  };

  it('is an accessible dialog, focuses its first control and locks page scroll', () => {
    open();
    expect(screen.getByRole('dialog', { name: 'عنوان' })).toHaveAttribute('aria-modal', 'true');
    expect(document.body.style.overflow).toBe('hidden');
    expect(screen.getByRole('button', { name: 'بستن' })).toHaveFocus();
  });

  it('closes on Escape, on the close button and on a backdrop click, but not on a click inside', async () => {
    const user = userEvent.setup();
    const onClose = open();
    await user.click(screen.getByLabelText('field'));
    expect(onClose).not.toHaveBeenCalled();
    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole('button', { name: 'بستن' }));
    expect(onClose).toHaveBeenCalledTimes(2);
    await user.click(screen.getByRole('dialog').parentElement);
    expect(onClose).toHaveBeenCalledTimes(3);
  });

  it('restores page scroll and the previous focus when it unmounts', () => {
    const trigger = document.createElement('button');
    document.body.appendChild(trigger);
    trigger.focus();
    const { unmount } = render(<Modal onClose={() => {}} title="x" />);
    unmount();
    expect(document.body.style.overflow).toBe('');
    expect(trigger).toHaveFocus();
    trigger.remove();
  });
});

describe('placeholders', () => {
  it('Empty shows its message and Loading announces progress with the requested rows', () => {
    render(
      <>
        <Empty text="چیزی نیست" />
        <Loading rows={4} />
      </>,
    );
    expect(screen.getByText('چیزی نیست')).toBeInTheDocument();
    const status = screen.getByRole('status', { name: 'در حال دریافت' });
    expect(status.children).toHaveLength(4);
  });
});
