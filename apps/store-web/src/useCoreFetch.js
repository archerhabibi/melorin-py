// Authenticated fetch against Core with one silent token refresh on 401 (split out of App.jsx, T-R11).
import { useCallback, useRef } from 'react';
import { setTokens } from './auth.js';

// Stable identity (so effects can depend on it); the token is read from a ref at call time, so callers never send a stale one.
export function useCoreFetch(base, accessToken, setAccessToken) {
  // Stable identity (so effects can list it as a dependency without re-running every render); the token is
  // read from a ref at call time, which also means callers never send a stale token.
  const accessTokenRef = useRef(accessToken);
  accessTokenRef.current = accessToken;
  const coreFetch = useCallback(
    async (path, options = {}) => {
      let token = accessTokenRef.current;
      let response = await fetch(`${base}${path}`, {
        ...options,
        credentials: 'include',
        headers: { ...(options.headers || {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      });
      if (response.status === 401) {
        {
          const rr = await fetch(`${base}/api/v1/auth/refresh`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: '{}',
          });
          if (rr.ok) {
            const pair = await rr.json();
            setTokens(pair);
            setAccessToken(pair.access_token);
            response = await fetch(`${base}${path}`, {
              ...options,
              headers: { ...(options.headers || {}), Authorization: `Bearer ${pair.access_token}` },
            });
          }
        }
      }
      return response;
    },
    [base, setAccessToken],
  );
  return coreFetch;
}
