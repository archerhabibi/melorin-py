let accessToken = "";
let refreshToken = "";

export function getAccessToken() { return accessToken; }
export function getRefreshToken() { return refreshToken; }
export function setTokens(pair) {
  accessToken = pair?.access_token || "";
  refreshToken = pair?.refresh_token || "";
}
export function clearTokens() { accessToken = ""; refreshToken = ""; }
