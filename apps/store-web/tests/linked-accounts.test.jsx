import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import LinkedAccounts from '../src/dashboard/DashboardLinking.tsx';

vi.mock('../src/GoogleSignIn.tsx', () => ({ GoogleSignInButton: () => <div>google-button</div> }));

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

function makeFetch({ method = 'password', unlink } = {}) {
  const calls = [];
  const fn = vi.fn(async (path, opts = {}) => {
    calls.push([opts.method || 'GET', path, opts.body ? JSON.parse(opts.body) : null]);
    if (path.endsWith('/linked-accounts'))
      return json({
        accounts: [{ id: 'a' }, { id: 'b' }],
        identities: [
          { id: 'i1', provider: 'telegram', label: '123456789', verified: true, linked_at: null },
          { id: 'i2', provider: 'google', label: 'me@example.com', verified: true, linked_at: null },
        ],
      });
    if (path.endsWith('/identity/reauth')) return json({ method });
    if (path.endsWith('/consolidation-status')) return json([]);
    if (path.endsWith('/unlink')) return unlink ? unlink() : json({ status: 'revoked' });
    return json({});
  });
  return { fn, calls };
}

describe('LinkedAccounts', () => {
  it('lists every login method and offers to add more', async () => {
    const { fn } = makeFetch();
    render(<LinkedAccounts coreFetch={fn} notify={() => {}} reload={() => {}} />);
    expect(await screen.findByText('123456789')).toBeInTheDocument();
    expect(screen.getByText('me@example.com')).toBeInTheDocument();
    expect(screen.getByText('google-button')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'درخواست یکپارچه‌سازی' })).toBeInTheDocument();
  });

  it('asks for the current password before unlinking and sends it', async () => {
    const { fn, calls } = makeFetch({ method: 'password' });
    render(<LinkedAccounts coreFetch={fn} notify={() => {}} reload={() => {}} />);
    await screen.findByText('123456789');
    await userEvent.click(screen.getAllByRole('button', { name: 'قطع اتصال' })[0]);
    await userEvent.type(screen.getByPlaceholderText('رمز فعلی'), 'pw-secret-1');
    await userEvent.click(screen.getByRole('button', { name: 'تأیید قطع اتصال' }));
    await waitFor(() => expect(calls.some(([, p]) => p.endsWith('/unlink'))).toBe(true));
    const body = calls.find(([, p]) => p.endsWith('/unlink'))[2];
    expect(body).toEqual({ identity_id: 'i1', current_password: 'pw-secret-1' });
  });

  it('uses an e-mail code for passwordless accounts', async () => {
    const { fn, calls } = makeFetch({ method: 'email_code' });
    render(<LinkedAccounts coreFetch={fn} notify={() => {}} reload={() => {}} />);
    await screen.findByText('123456789');
    await userEvent.click(screen.getAllByRole('button', { name: 'قطع اتصال' })[0]);
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'ارسال کد' }));
    expect(calls.some(([m, p]) => m === 'POST' && p.endsWith('/reauth/email/start'))).toBe(true);
    await userEvent.type(screen.getByPlaceholderText('کد ایمیل'), '123456');
    await userEvent.click(screen.getByRole('button', { name: 'تأیید قطع اتصال' }));
    await waitFor(() => expect(calls.find(([, p]) => p.endsWith('/unlink'))[2].reauth_code).toBe('123456'));
  });

  it('never merges silently: a conflict asks for an explicit confirmation', async () => {
    const conflict = () =>
      json({ error: { code: 'IDENTITY_IN_USE', message: 'x', details: { operation_id: 'op-1' } } }, 409);
    const { fn, calls } = makeFetch({ unlink: conflict });
    render(<LinkedAccounts coreFetch={fn} notify={() => {}} reload={() => {}} />);
    await screen.findByText('123456789');
    await userEvent.click(screen.getAllByRole('button', { name: 'قطع اتصال' })[0]);
    await userEvent.type(screen.getByPlaceholderText('رمز فعلی'), 'pw-secret-1');
    await userEvent.click(screen.getByRole('button', { name: 'تأیید قطع اتصال' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('به پروفایل دیگری تعلق دارد');
    await userEvent.click(screen.getByRole('button', { name: 'تأیید اتصال' }));
    await waitFor(() =>
      expect(calls.some(([, p, b]) => p.endsWith('/link/confirm') && b.operation_id === 'op-1')).toBe(true),
    );
  });
});
