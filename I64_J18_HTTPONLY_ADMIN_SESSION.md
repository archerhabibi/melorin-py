# I64: J18 HttpOnly Admin Session

The admin refresh session is no longer memory-only and no longer exposed to
JavaScript storage. Core sets the refresh token in a Secure, HttpOnly,
SameSite=Lax cookie scoped to `/api/v1/auth`; the short-lived access token
remains memory-only.

On an admin page reload, the web app silently calls Core's refresh endpoint
with credentials and restores only the in-memory access token. Logout revokes
the refresh token and deletes the cookie. The JSON refresh-token body remains
optional for backward-compatible non-browser clients.
