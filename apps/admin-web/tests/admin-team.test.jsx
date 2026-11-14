import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AdminTeamView from '../src/AdminTeamView.tsx';
import AcceptInvite, { inviteToken, isInviteHash, passwordChecks } from '../src/AcceptInvite.tsx';
import { extraRoutes } from '../src/AdminExtra.tsx';
import { SECTION_AREA, can, sectionAllowed } from '../src/adminAccess.ts';

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
const BASE = 'http://core.test';

const ROLES = ['owner', 'manager', 'finance', 'support', 'viewer'].map((key) => ({
  key,
  label: { owner: 'مالک', manager: 'مدیر عملیات', finance: 'مالی', support: 'پشتیبانی', viewer: 'مشاهده‌گر' }[key],
  description: `توضیح ${key}`,
  permissions: key === 'owner' ? ['orders:rw', 'admins:rw', 'system:rw'] : ['orders:r'],
}));
const ADMINS = [
  {
    id: 'a1',
    email: 'boss@example.com',
    display_name: 'رئیس',
    role: 'owner',
    role_label: 'مالک',
    state: 'active',
    is_active: true,
    totp_enabled: true,
    is_self: true,
    created_at: '2026-01-01T00:00:00Z',
    last_login_at: '2026-11-01T10:00:00Z',
    invite_expires_at: null,
  },
  {
    id: 'a2',
    email: 'sara@example.com',
    display_name: 'سارا',
    role: 'support',
    role_label: 'پشتیبانی',
    state: 'invited',
    is_active: false,
    totp_enabled: false,
    is_self: false,
    created_at: '2026-11-10T00:00:00Z',
    last_login_at: null,
    invite_expires_at: '2026-11-13T00:00:00Z',
  },
];

function setupTeam({ failInvite = false } = {}) {
  const calls = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, o = {}) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '');
    calls.push([o.method || 'GET', path, o.body]);
    if (path === '/api/v1/admin/admins' && o.method === 'POST')
      return failInvite
        ? json({ error: { code: 'ADMIN_EXISTS', message: 'x' } }, 409)
        : json(
            {
              admin: { ...ADMINS[1], email: JSON.parse(o.body).email },
              invite_path: '/#/accept-invite?t=TOKEN123',
              invite_url: 'https://admin.example.com/#/accept-invite?t=TOKEN123',
              expires_at: '2026-11-15T00:00:00Z',
              emailed: false,
            },
            201,
          );
    if (path === '/api/v1/admin/admins/roles') return json(ROLES);
    if (path === '/api/v1/admin/admins') return json(ADMINS);
    return json({ ok: true });
  });
  const toast = vi.fn();
  render(<AdminTeamView api={{ base: BASE }} toast={toast} />);
  return { calls, toast };
}

describe('admin access table (mirror of the server rules)', () => {
  it('every screen of the nav has a permission area, and unknown screens fall to owner-only', () => {
    expect(SECTION_AREA['تیم مدیریت']).toBe('admins');
    expect(SECTION_AREA['تنظیمات']).toBe('system');
    expect(sectionAllowed(['orders:r'], 'screen-nobody-knows')).toBe(false);
    expect(sectionAllowed(['system:rw'], 'screen-nobody-knows')).toBe(true);
  });

  it('permissions not loaded yet show everything; an empty list shows nothing', () => {
    expect(can(undefined, 'orders')).toBe(true);
    expect(can([], 'orders')).toBe(false);
    expect(can(['orders:r'], 'orders')).toBe(true);
    expect(can(['orders:r'], 'orders', true)).toBe(false);
    expect(can(['orders:rw'], 'orders', true)).toBe(true);
    expect(can(['orders:rw'], 'order')).toBe(false); // prefix lookalike
  });

  it('the app nav and the access table agree', async () => {
    const { readFileSync } = await import('node:fs');
    const src = readFileSync('src/adminNav.ts', 'utf8');
    const navNames = [...src.matchAll(/\['([^']+)', [A-Za-z]+, '[a-z-]+'\]/g)].map((m) => m[1]);
    expect(navNames.length).toBeGreaterThan(25);
    expect(navNames.filter((n) => !(n in SECTION_AREA))).toEqual([]);
  });

  it('registers both new screens', () => {
    expect(Object.keys(extraRoutes)).toEqual(expect.arrayContaining(['تیم مدیریت', 'حساب من']));
  });
});

describe('admin team screen', () => {
  it('lists the team with state and role', async () => {
    setupTeam();
    expect(await screen.findByText('boss@example.com', { exact: false })).toBeInTheDocument();
    expect(screen.getAllByText('در انتظار پذیرش دعوت').length).toBeGreaterThan(0);
    expect(screen.getByText('شما')).toBeInTheDocument();
  });

  it('invites an admin and shows the one-time link', async () => {
    const { calls } = setupTeam();
    await screen.findByText('سارا');
    await userEvent.click(screen.getByRole('button', { name: /دعوت ادمین/ }));
    await userEvent.type(screen.getByPlaceholderText('name@example.com'), 'new@example.com');
    await userEvent.click(screen.getByRole('radio', { name: 'مالی' }));
    await userEvent.click(screen.getByRole('button', { name: 'ساخت و ارسال دعوت' }));
    expect(await screen.findByDisplayValue(/accept-invite\?t=TOKEN123/)).toBeInTheDocument();
    const post = calls.find(([m, p]) => m === 'POST' && p === '/api/v1/admin/admins');
    expect(JSON.parse(post[2])).toEqual({ email: 'new@example.com', display_name: null, role: 'finance' });
    expect(screen.getByText(/ایمیل ارسال نشد/)).toBeInTheDocument();
  });

  it('does not allow sending an invite to an invalid e-mail', async () => {
    setupTeam();
    await screen.findByText('سارا');
    await userEvent.click(screen.getByRole('button', { name: /دعوت ادمین/ }));
    await userEvent.type(screen.getByPlaceholderText('name@example.com'), 'not-an-email');
    expect(screen.getByRole('button', { name: 'ساخت و ارسال دعوت' })).toBeDisabled();
  });

  it('shows a readable server error when inviting fails', async () => {
    setupTeam({ failInvite: true });
    await screen.findByText('سارا');
    await userEvent.click(screen.getByRole('button', { name: /دعوت ادمین/ }));
    await userEvent.type(screen.getByPlaceholderText('name@example.com'), 'boss@example.com');
    await userEvent.click(screen.getByRole('button', { name: 'ساخت و ارسال دعوت' }));
    expect(await screen.findByText('این ایمیل از قبل ادمین است.')).toBeInTheDocument();
  });

  it('your own row has no dangerous actions and a locked role', async () => {
    setupTeam();
    await userEvent.click(await screen.findByText('رئیس'));
    expect(await screen.findByText(/نقش حساب خودتان را نمی‌توانید تغییر دهید/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /حذف از تیم/ })).not.toBeInTheDocument();
  });

  it('changing a role sends only the patch to that admin', async () => {
    const { calls } = setupTeam();
    await userEvent.click(await screen.findByText('سارا'));
    await userEvent.click(await screen.findByRole('radio', { name: 'مدیر عملیات' }));
    await userEvent.click(screen.getByRole('button', { name: 'ذخیره' }));
    await waitFor(() => expect(calls.some(([m, p]) => m === 'PATCH' && p === '/api/v1/admin/admins/a2')).toBe(true));
    const patch = calls.find(([m]) => m === 'PATCH');
    expect(JSON.parse(patch[2])).toEqual({ display_name: 'سارا', role: 'manager' });
  });
});

describe('accept invite page', () => {
  it('reads the token only from the URL fragment', () => {
    expect(isInviteHash('#/accept-invite?t=abc')).toBe(true);
    expect(isInviteHash('#/accept-invite')).toBe(true);
    expect(isInviteHash('#/accept-invitex')).toBe(false);
    expect(isInviteHash('#/orders')).toBe(false);
    expect(inviteToken('#/accept-invite?t=abc_DEF-1')).toBe('abc_DEF-1');
    expect(inviteToken('#/accept-invite')).toBe('');
  });

  it('mirrors the password rules', () => {
    const ok = (p, e) => passwordChecks(p, e).every((c) => c.ok);
    expect(ok('Correct-Horse-9', 'a@b.co')).toBe(true);
    expect(ok('short1A!', 'a@b.co')).toBe(false);
    expect(ok('alllowercaseletters', 'a@b.co')).toBe(false);
    expect(ok('Xx-sara.admin-9A', 'sara.admin@example.com')).toBe(false);
  });

  it('walks the three steps and ends on the sign-in hint', async () => {
    window.location.hash = '#/accept-invite?t=' + 'x'.repeat(30);
    const calls = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, o = {}) => {
      const path = String(url).replace(/^https?:\/\/[^/]+/, '');
      calls.push([path, o.body]);
      if (path.endsWith('/inspect'))
        return json({
          email: 'new@example.com',
          display_name: 'سارا',
          role: 'support',
          role_label: 'پشتیبانی',
          expires_at: '2026-11-15T00:00:00Z',
        });
      if (path.endsWith('/enroll'))
        return json({ secret: 'JBSWY3DPEHPK3PXP', otpauth_url: 'otpauth://x', qr_data_uri: 'data:image/svg+xml,x' });
      if (path.endsWith('/accept')) return json({ ok: true, email: 'new@example.com' });
      return json({}, 404);
    });
    render(<AcceptInvite base={BASE} />);
    expect(await screen.findByText('new@example.com')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'شروع راه‌اندازی' }));
    expect(await screen.findByText('JBSWY3DPEHPK3PXP')).toBeInTheDocument();

    const submit = screen.getByRole('button', { name: 'فعال‌سازی حساب' });
    expect(submit).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/رمز عبور تازه/), 'Correct-Horse-9');
    await userEvent.type(screen.getByLabelText('تکرار رمز عبور'), 'Correct-Horse-9');
    await userEvent.type(screen.getByLabelText(/کد ۶ رقمی/), '123456');
    expect(submit).toBeEnabled();
    await userEvent.click(submit);
    expect(await screen.findByText('حساب شما آماده است')).toBeInTheDocument();
    const accept = calls.find(([p]) => p.endsWith('/accept'));
    expect(JSON.parse(accept[1])).toEqual({ token: 'x'.repeat(30), password: 'Correct-Horse-9', totp_code: '123456' });
    // enrol is called exactly once (a second call would replace the seed shown in the QR code)
    expect(calls.filter(([p]) => p.endsWith('/enroll'))).toHaveLength(1);
    window.location.hash = '';
  });

  it('shows the invalid screen for an unknown or used link', async () => {
    window.location.hash = '#/accept-invite?t=' + 'y'.repeat(30);
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ error: { code: 'INVITE_INVALID', message: 'x' } }, 400));
    render(<AcceptInvite base={BASE} />);
    expect(await screen.findByText('لینک دعوت معتبر نیست')).toBeInTheDocument();
    window.location.hash = '';
  });

  it('shows the invalid screen when the link carries no token', () => {
    window.location.hash = '#/accept-invite';
    render(<AcceptInvite base={BASE} />);
    expect(screen.getByText('لینک دعوت معتبر نیست')).toBeInTheDocument();
    window.location.hash = '';
  });
});
