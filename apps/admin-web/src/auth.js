let accessToken = "";

export function getAccessToken() { return accessToken; }
export function getRefreshToken() { return ""; }
export function setTokens(pair) {
  accessToken = pair?.access_token || "";
}
export function clearTokens() { accessToken = ""; }
