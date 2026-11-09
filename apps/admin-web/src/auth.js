export { getAccessToken, setTokens, clearTokens } from '@melorin/web-kit/auth.js';

// Kept for backwards compatibility: the refresh token is an httpOnly cookie and is never readable from JS.
export const getRefreshToken = () => '';
