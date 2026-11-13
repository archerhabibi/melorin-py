import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AdminAuth from '../src/AdminAuth.tsx';
import { clearTokens, getAccessToken } from '../src/auth.ts';

vi.mock('../src/GoogleSignIn.tsx', () => ({
  GoogleSignInButton: () => null,
  useGoogleConfig: () => null,
}));

const reply = (status, body) =>
  Promise.resolve({ ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) });
const apiError = (status, code) => reply(status, { error: { code, message: 'x' } });

async function fillAndSubmit({ totp = '' } = {}) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('ایمیل مدیر'), 'root@example.com');
  await user.type(screen.getByLabelText('رمز عبور'), 'a-long-enough-password');
  if (totp) await user.type(screen.getByLabelText('کد TOTP'), totp);
  await user.click(screen.getByRole('button', { name: 'ورود به داشبورد' }));
  return user;
}

describe('AdminAuth sign-in failures', () => {
  beforeEach(() => {
    clearTokens();
    vi.stubGlobal('fetch', vi.fn());
  });
  afterEach(() => vi.unstubAllGlobals());

  it('wrong e-mail/password: red notice under the password, e-mail + password flagged, TOTP untouched', async () => {
    fetch.mockReturnValueOnce(apiError(401, 'INVALID_CREDENTIALS'));
    render(<AdminAuth base="" onSuccess={() => {}} />);
    await fillAndSubmit({ totp: '123456' });

    const notice = await screen.findByTestId('login-failure-credentials');
    expect(notice).toHaveTextContent('ایمیل یا رمز عبور نادرست است.');
    expect(screen.getByLabelText('ایمیل مدیر')).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByLabelText('رمز عبور')).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByLabelText('کد TOTP')).not.toHaveAttribute('aria-invalid');
    expect(screen.getByLabelText('کد TOTP')).toHaveValue('123456');
    expect(screen.queryByTestId('login-failure-totp')).toBeNull();
    expect(screen.getByLabelText('رمز عبور')).toHaveFocus();
  });

  it('wrong TOTP: amber notice under the TOTP field, a different message, the code is cleared and focused', async () => {
    fetch.mockReturnValueOnce(apiError(401, 'TOTP_INVALID'));
    render(<AdminAuth base="" onSuccess={() => {}} />);
    await fillAndSubmit({ totp: '000000' });

    const notice = await screen.findByTestId('login-failure-totp');
    expect(notice).toHaveTextContent('کد TOTP نادرست یا منقضی است.');
    expect(notice).not.toHaveTextContent('ایمیل یا رمز عبور نادرست است.');
    expect(notice).toHaveAttribute('data-code', 'TOTP_INVALID');
    const field = screen.getByLabelText('کد TOTP');
    expect(field).toHaveAttribute('aria-invalid', 'true');
    expect(field).toHaveAttribute('data-tone', 'warning');
    expect(field).toHaveAttribute('aria-describedby', 'login-failure-totp');
    expect(field).toHaveValue('');
    expect(field).toHaveFocus();
    // e-mail and password are NOT blamed
    expect(screen.getByLabelText('ایمیل مدیر')).not.toHaveAttribute('aria-invalid');
    expect(screen.getByLabelText('رمز عبور')).not.toHaveAttribute('aria-invalid');
    expect(screen.queryByTestId('login-failure-credentials')).toBeNull();
  });

  it('missing TOTP asks for the code and keeps what was typed elsewhere', async () => {
    fetch.mockReturnValueOnce(apiError(401, 'TOTP_REQUIRED'));
    render(<AdminAuth base="" onSuccess={() => {}} />);
    await fillAndSubmit();
    expect(await screen.findByTestId('login-failure-totp')).toHaveTextContent('کد TOTP را وارد کنید.');
    expect(screen.getByLabelText('رمز عبور')).toHaveValue('a-long-enough-password');
    expect(screen.getByLabelText('کد TOTP')).toHaveFocus();
  });

  it('reused TOTP says so and asks to wait for the next code', async () => {
    fetch.mockReturnValueOnce(apiError(401, 'TOTP_REPLAYED'));
    render(<AdminAuth base="" onSuccess={() => {}} />);
    await fillAndSubmit({ totp: '123456' });
    expect(await screen.findByTestId('login-failure-totp')).toHaveTextContent('قبلاً استفاده شده');
  });

  it('a throttled account, a dead network and a 502 are general notices, never "wrong password"', async () => {
    for (const [mock, text] of [
      [() => apiError(429, 'ACCOUNT_LOGIN_THROTTLED'), 'موقتاً محدود شده'],
      [() => Promise.reject(new TypeError('Failed to fetch')), 'ارتباط با سرور برقرار نشد'],
      [() => reply(502, {}), 'سرور موقتاً پاسخ نمی‌دهد'],
    ]) {
      fetch.mockReset();
      fetch.mockImplementationOnce(mock); // lazy: a rejected promise built earlier would be "unhandled" until fetch runs
      const { unmount } = render(<AdminAuth base="" onSuccess={() => {}} />);
      await fillAndSubmit({ totp: '123456' });
      const notice = await screen.findByTestId('login-failure-form');
      expect(notice).toHaveTextContent(text);
      expect(notice).not.toHaveTextContent('ایمیل یا رمز عبور نادرست است.');
      expect(screen.getByLabelText('رمز عبور')).not.toHaveAttribute('aria-invalid');
      unmount();
    }
  });

  it('editing the flagged field dismisses its notice; a new attempt starts clean', async () => {
    fetch.mockReturnValueOnce(apiError(401, 'TOTP_INVALID'));
    render(<AdminAuth base="" onSuccess={() => {}} />);
    const user = await fillAndSubmit({ totp: '000000' });
    await screen.findByTestId('login-failure-totp');
    await user.type(screen.getByLabelText('کد TOTP'), '1');
    expect(screen.queryByTestId('login-failure-totp')).toBeNull();
    expect(screen.getByLabelText('کد TOTP')).not.toHaveAttribute('aria-invalid');
  });

  it('accepts a code pasted with a space or Persian digits and sends plain ASCII digits', async () => {
    fetch.mockReturnValueOnce(reply(200, { access_token: 'tok', is_admin: true }));
    const onSuccess = vi.fn();
    render(<AdminAuth base="" onSuccess={onSuccess} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('ایمیل مدیر'), 'root@example.com');
    await user.type(screen.getByLabelText('رمز عبور'), 'a-long-enough-password');
    await user.type(screen.getByLabelText('کد TOTP'), '۴۵۲ ۶۴۸');
    expect(screen.getByLabelText('کد TOTP')).toHaveValue('452648');
    await user.click(screen.getByRole('button', { name: 'ورود به داشبورد' }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(JSON.parse(fetch.mock.calls[0][1].body).totp_code).toBe('452648');
    expect(getAccessToken()).toBe('tok');
  });
});
