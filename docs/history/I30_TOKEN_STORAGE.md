# I30: browser token storage

Access and refresh tokens are now held in module memory only. The Web clients
no longer persist bearer tokens in `localStorage`, reducing the impact of a
browser XSS reading durable credentials.

Reloading a page intentionally requires signing in again. A production
follow-up can move refresh rotation to an HttpOnly, Secure, SameSite cookie
once the API exposes cookie-based login and refresh responses.
