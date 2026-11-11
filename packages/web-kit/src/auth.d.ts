/** In-memory access-token store (the refresh token lives in an httpOnly cookie). */
export function getAccessToken(): string;
export function setTokens(pair?: { access_token?: string } | null): void;
export function clearTokens(): void;
