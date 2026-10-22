import { beforeEach, describe, expect, it } from 'vitest';
import { clearTokens, getAccessToken, setTokens } from '../src/auth.js';

describe('admin-web in-memory session token', () => {
  beforeEach(() => clearTokens());

  it('starts empty and never touches browser storage', () => {
    expect(getAccessToken()).toBe('');
    setTokens({ access_token: 'abc' });
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it('keeps the access token from a token pair and clears it on sign-out', () => {
    setTokens({ access_token: 'abc', refresh_token: 'never-kept-in-js' });
    expect(getAccessToken()).toBe('abc');
    clearTokens();
    expect(getAccessToken()).toBe('');
  });

  it.each([[undefined], [null], [{}]])('treats a malformed pair (%j) as signed out', (pair) => {
    setTokens({ access_token: 'abc' });
    setTokens(pair);
    expect(getAccessToken()).toBe('');
  });
});
