import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import IdentityHubView from '../src/IdentityHubView.jsx';
import { legacyHash } from '../src/infra.jsx';
import { DialogHost } from '../src/ui.jsx';

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
const card = (id, name) => ({ id, display_name: name, email: `${name}@example.com`, orders: 1, providers: ['google'] });
const review = (over = {}) => ({
  id: 'r1',
  email: 'a@example.com',
  provider: 'google',
  reason: 'google_account_belongs_to_other_user',
  status: 'open',
  auto: false,
  resolution_note: null,
  created_at: '2026-10-27T08:00:00Z',
  source_user: card('u1', 'Source'),
  candidates: [card('u2', 'Other')],
  ...over,
});
const device = {
  id: 'd1',
  status: 'active',
  user: { id: 'u1', display_name: 'Ali', email: 'ali@example.com' },
  store_id: 's1',
  store_name: 'Main',
  telegram_id: 4242,
  label: 'Chrome · Windows',
  last_ip: '203.0.113.7',
  uses: 3,
  last_seen_at: '2026-10-27T10:00:00Z',
  expires_at: '2026-12-27T10:00:00Z',
  revoked_at: null,
};
const merge = {
  id: 'm1',
  created_at: '2026-10-27T09:00:00Z',
  rule: 'shell_into_other',
  providers: ['google'],
  keeper: { id: 'k1111111', display_name: 'Keep', email: 'k@example.com' },
  shell: { id: 's2222222', display_name: 'Empty', email: null },
};

function setup(reviews) {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '');
    if (path.includes('/identity-link-reviews')) return json(reviews);
    if (path.includes('/trusted-devices/summary'))
      return json({ active_devices: 1, accounts: 1, revoked_devices: 0, auto_merges_30d: 1 });
    if (path.includes('/trusted-devices')) return json([device]);
    if (path.includes('/identity-auto-merges')) return json([merge]);
    return json([]);
  });
  render(
    <>
      <IdentityHubView api={{ base: 'http://core.test' }} toast={vi.fn()} />
      <DialogHost />
    </>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState(null, '', '/');
});

describe('admin «هویت» hub', () => {
  it('opens on the manual review queue and shows how many conflicts wait', async () => {
    setup([review()]);
    expect(await screen.findByText('Source')).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /نیاز به بررسی/ })).toHaveAttribute('aria-checked', 'true');
    expect(await screen.findByRole('radio', { name: /نیاز به بررسی\s*۱|نیاز به بررسی\s*1/ })).toBeInTheDocument();
  });

  it('keeps conflicts Core settled itself out of the manual queue', async () => {
    setup([
      review({
        id: 'r2',
        auto: true,
        status: 'linked',
        resolution_note: 'auto:shell_into_other',
        source_user: card('u9', 'AutoSettled'),
      }),
    ]);
    expect(await screen.findByText('صف بررسی خالی است')).toBeInTheDocument();
    expect(screen.queryByText('AutoSettled')).toBeNull();
  });

  it('switches to the automatic merges report and to trusted devices', async () => {
    setup([review()]);
    await userEvent.click(await screen.findByRole('radio', { name: 'انجام‌شده خودکار' }));
    expect(await screen.findByText('Empty')).toBeInTheDocument();
    expect(screen.queryByRole('radio', { name: 'ادغام‌های خودکار' })).toBeNull(); // no second tab bar inside the hub
    expect(window.location.hash).toBe('#/identity?tab=auto');
    await userEvent.click(screen.getByRole('radio', { name: 'دستگاه‌های مورداعتماد' }));
    expect(await screen.findByText('Chrome · Windows')).toBeInTheDocument();
    await waitFor(() => expect(window.location.hash).toBe('#/identity?tab=devices'));
  });

  it('honours a deep link to a tab', async () => {
    window.history.replaceState(null, '', '/#/identity?tab=devices');
    setup([]);
    expect(await screen.findByText('Chrome · Windows')).toBeInTheDocument();
  });
});

describe('old bookmark of the former separate screen', () => {
  it('#/identity-auto lands on the devices tab of the hub', () => {
    expect(legacyHash('#/identity-auto')).toBe('#/identity?tab=devices');
    expect(legacyHash('#/identity')).toBeNull();
  });
});
