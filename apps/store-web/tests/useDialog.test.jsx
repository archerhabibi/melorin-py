import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { backdropProps, focusOnMount, useDialog } from '../src/useDialog.js';

function Box({ onClose, label, children }) {
  const ref = useDialog(onClose);
  return (
    <div {...backdropProps(onClose)} data-testid={`backdrop-${label}`}>
      <div ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label={label}>
        <button>first-{label}</button>
        <input aria-label={`field-${label}`} />
        <button>last-{label}</button>
        {children}
      </div>
    </div>
  );
}

describe('useDialog', () => {
  it('moves focus inside, traps Tab both ways, and restores focus on close', async () => {
    const user = userEvent.setup();
    const Host = ({ open }) => (
      <>
        <button>opener</button>
        {open && <Box label="a" onClose={() => {}} />}
      </>
    );
    const { rerender } = render(<Host open={false} />);
    screen.getByText('opener').focus();
    rerender(<Host open />);
    expect(screen.getByText('first-a')).toHaveFocus();
    await user.tab();
    await user.tab();
    expect(screen.getByText('last-a')).toHaveFocus();
    await user.tab();
    expect(screen.getByText('first-a')).toHaveFocus();
    await user.tab({ shift: true });
    expect(screen.getByText('last-a')).toHaveFocus();
    rerender(<Host open={false} />);
    expect(screen.getByText('opener')).toHaveFocus();
  });

  it('prefers [data-autofocus] for the initial focus', () => {
    function WithAuto() {
      const ref = useDialog(() => {});
      return (
        <div ref={ref} tabIndex={-1} role="dialog" aria-label="x">
          <button>one</button>
          <input data-autofocus aria-label="target" />
        </div>
      );
    }
    render(<WithAuto />);
    expect(screen.getByLabelText('target')).toHaveFocus();
  });

  it('Escape closes only the topmost dialog', async () => {
    const user = userEvent.setup();
    const outer = vi.fn();
    const inner = vi.fn();
    render(
      <>
        <Box label="outer" onClose={outer} />
        <Box label="inner" onClose={inner} />
      </>,
    );
    await user.keyboard('{Escape}');
    expect(inner).toHaveBeenCalledTimes(1);
    expect(outer).not.toHaveBeenCalled();
  });

  it('locks background scroll while open and releases it after the last dialog closes', () => {
    const a = render(<Box label="a" onClose={() => {}} />);
    const b = render(<Box label="b" onClose={() => {}} />);
    expect(document.body.style.overflow).toBe('hidden');
    a.unmount();
    expect(document.body.style.overflow).toBe('hidden');
    b.unmount();
    expect(document.body.style.overflow).toBe('');
  });

  it('backdrop closes only when the press starts on the backdrop itself', async () => {
    const user = userEvent.setup();
    const close = vi.fn();
    render(<Box label="a" onClose={close} />);
    await user.click(screen.getByText('first-a'));
    expect(close).not.toHaveBeenCalled();
    await user.click(screen.getByTestId('backdrop-a'));
    expect(close).toHaveBeenCalledTimes(1);
  });

  it('focusOnMount focuses the element once and tolerates null', () => {
    expect(() => focusOnMount(null)).not.toThrow();
    render(<input aria-label="edit" ref={focusOnMount} />);
    expect(screen.getByLabelText('edit')).toHaveFocus();
  });
});
