import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { StoreErrorBoundary } from '../src/ErrorBoundary.tsx';

vi.mock('../src/App.tsx', () => ({
  default: function FailingApp() {
    throw new Error('application rendering failed');
  },
}));

function FailingView() {
  throw new Error('view rendering failed');
}

afterEach(() => vi.restoreAllMocks());

describe('storefront error recovery', () => {
  it('shows a recovery action after a rendering error', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const retry = vi.fn();
    render(
      <StoreErrorBoundary onRetry={retry}>
        <FailingView />
      </StoreErrorBoundary>,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('مشکلی در نمایش صفحه پیش آمد');
    await userEvent.click(screen.getByRole('button', { name: 'بارگذاری دوباره' }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it('renders the storefront normally when no error occurs', () => {
    render(
      <StoreErrorBoundary>
        <p>plans</p>
      </StoreErrorBoundary>,
    );
    expect(screen.getByText('plans')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('shows recovery when the application mounted by the real entry point fails', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const root = document.createElement('div');
    root.id = 'root';
    document.body.appendChild(root);
    await import('../src/main.tsx');
    expect(await screen.findByRole('alert')).toHaveTextContent('مشکلی در نمایش صفحه پیش آمد');
    root.remove();
  });
});
