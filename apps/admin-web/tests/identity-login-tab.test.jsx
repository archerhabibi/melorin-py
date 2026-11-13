import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import IdentityHubView from '../src/IdentityHubView.tsx';

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });

describe('هویت › روش‌های ورود', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.replaceState(null, '', '/');
  });

  it('hosts the Google and Telegram sign-in settings (moved out of Settings) and deep-links with ?tab=login', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url) => (String(url).includes('identity-link-reviews') ? json([]) : json({}))),
    );
    render(<IdentityHubView api={{ base: '' }} toast={vi.fn()} />);
    await userEvent.click(await screen.findByRole('radio', { name: 'روش‌های ورود' }).catch(() => screen.findByText('روش‌های ورود')));
    expect(window.location.hash).toBe('#/identity?tab=login');
  });
});
