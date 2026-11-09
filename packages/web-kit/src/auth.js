// In-memory access-token store shared by admin-web and store-web.
// The refresh token lives in an httpOnly cookie and is never readable from JS.
let accessToken = "";

export function getAccessToken() {
  return accessToken;
}
export function setTokens(pair) {
  accessToken = pair?.access_token || "";
}
export function clearTokens() {
  accessToken = "";
}
