import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Settings from '../src/SettingsView.tsx';

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
const integrations = {
  admin_access: { enabled: false, ips: [], your_ip: '203.0.113.7' },
  email: { enabled: false },
  backup: { s3: { enabled: false } },
};

afterEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState(null, '', '/');
});

describe('Settings: admin IP allowlist lives in its own security tab', () => {
  const mount = () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const path = String(url).replace(/^https?:\/\/[^/]+/, '');
      if (path.startsWith('/api/v1/admin/integrations')) return json(integrations);
      return json([]);
    });
    render(<Settings api={{ base: 'http://core.test' }} toast={vi.fn()} />);
  };

  it('keeps the IP allowlist off the integrations tab', async () => {
    mount();
    await waitFor(() => expect(screen.getByText('امنیت دسترسی ادمین')).toBeInTheDocument());
    expect(screen.queryByText('دسترسی ادمین (محدودیت IP)')).not.toBeInTheDocument();
  });

  it('shows the IP allowlist on the security tab', async () => {
    mount();
    await userEvent.click(await screen.findByText('امنیت دسترسی ادمین'));
    expect(await screen.findByText('دسترسی ادمین (محدودیت IP)')).toBeInTheDocument();
    expect(window.location.hash).toBe('#/settings?tab=security');
  });
});
