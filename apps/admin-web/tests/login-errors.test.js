import { describe, expect, it } from 'vitest';
import {
  codeFromResponse,
  describeLoginFailure,
  failureFromError,
  LoginRequestError,
  sanitizeTotp,
} from '../src/loginErrors.ts';

describe('login failure messages', () => {
  it('tells a wrong password, a wrong TOTP, a missing TOTP and a reused TOTP apart', () => {
    const creds = describeLoginFailure('INVALID_CREDENTIALS', 401);
    const invalid = describeLoginFailure('TOTP_INVALID', 401);
    const missing = describeLoginFailure('TOTP_REQUIRED', 401);
    const replay = describeLoginFailure('TOTP_REPLAYED', 401);

    expect(creds.area).toBe('credentials');
    expect([invalid.area, missing.area, replay.area]).toEqual(['totp', 'totp', 'totp']);
    expect(new Set([creds.title, invalid.title, missing.title, replay.title]).size).toBe(4);
    // a TOTP failure never claims the e-mail or password is wrong
    for (const f of [invalid, missing, replay]) expect(f.title).not.toContain('ایمیل یا رمز');
    expect(creds.title).not.toContain('TOTP');
  });

  it('uses different colours for "fix this" and "wait / try a code"', () => {
    expect(describeLoginFailure('INVALID_CREDENTIALS').tone).toBe('danger');
    expect(describeLoginFailure('TOTP_INVALID').tone).toBe('warning');
  });

  it('clears the typed code only when it is useless (wrong or already used)', () => {
    expect(describeLoginFailure('TOTP_INVALID').clearTotp).toBe(true);
    expect(describeLoginFailure('TOTP_REPLAYED').clearTotp).toBe(true);
    expect(describeLoginFailure('TOTP_REQUIRED').clearTotp).toBeFalsy();
  });

  it.each([
    ['ACCOUNT_LOGIN_THROTTLED', 429],
    ['RATE_LIMITED', 429],
    ['NETWORK_ERROR', 0],
    ['SERVER_ERROR', 500],
    ['ADMIN_IP_NOT_ALLOWED', 403],
    ['ADMIN_2FA_REQUIRED', 403],
  ])('%s is a general notice, never "wrong password"', (code, status) => {
    const f = describeLoginFailure(code, status);
    expect(f.area).toBe('form');
    expect(f.title).not.toContain('ایمیل یا رمز');
  });

  it('treats any 5xx as a server problem and unknown codes as a neutral failure that names the code', () => {
    expect(describeLoginFailure('WHATEVER', 503).code).toBe('SERVER_ERROR');
    const unknown = describeLoginFailure('SOMETHING_NEW', 400);
    expect(unknown.title).not.toContain('ایمیل یا رمز');
    expect(unknown.hint).toContain('SOMETHING_NEW');
  });

  it('keeps the Google-specific messages on the Google channel only', () => {
    expect(describeLoginFailure('NOT_ADMIN', 200, 'google').title).toContain('Google');
    expect(describeLoginFailure('GOOGLE_NONCE_INVALID', 400, 'google').hint).toBeTruthy();
    expect(describeLoginFailure('TOTP_INVALID', 401, 'google').area).toBe('totp');
    expect(describeLoginFailure('GOOGLE_FOO', 400, 'google').title).toContain('Google');
  });

  it('maps unexpected exceptions to a neutral failure instead of a credentials error', () => {
    expect(failureFromError(new Error('boom')).area).toBe('form');
    expect(failureFromError(new LoginRequestError('TOTP_INVALID', 401)).code).toBe('TOTP_INVALID');
  });
});

describe('codeFromResponse', () => {
  it('prefers the API code, then derives one from the status', () => {
    expect(codeFromResponse(401, { error: { code: 'TOTP_INVALID' } }, 'X')).toBe('TOTP_INVALID');
    expect(codeFromResponse(401, { code: 'FLAT' }, 'X')).toBe('FLAT');
    expect(codeFromResponse(429, {}, 'X')).toBe('RATE_LIMITED');
    expect(codeFromResponse(502, {}, 'X')).toBe('SERVER_ERROR');
    expect(codeFromResponse(400, null, 'LOGIN_FAILED')).toBe('LOGIN_FAILED');
  });
});

describe('sanitizeTotp', () => {
  it.each([
    ['452 648', '452648'],
    ['452-648', '452648'],
    [' 452648\n', '452648'],
    ['۴۵۲۶۴۸', '452648'],
    ['٤٥٢٦٤٨', '452648'],
    ['12abc34', '1234'],
    ['', ''],
  ])('%j -> %j', (raw, expected) => {
    expect(sanitizeTotp(raw)).toBe(expected);
  });

  it('never keeps more than 8 digits', () => {
    expect(sanitizeTotp('1234567890')).toBe('12345678');
  });
});
