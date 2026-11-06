"""PasarGuard transport: auth (password token / X-Api-Key), request plumbing, error classification, health.

Everything here is panel-generic; the feature mixins (users, admins, nodes, ...) only call ``_req``."""

import datetime as dt
import json
import time
from urllib.parse import urlsplit

import httpx

from melorin.modules.vpn.adapters.base import ErrorKind, PanelError

_TOKEN_TTL = 50 * 60
_TOKENS: dict[tuple[str, str], tuple[str, float]] = {}  # (base, username) -> (token, expires)


def _error_detail(text: str) -> str:
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return (text or "").strip()[:300]
    if isinstance(data, dict):
        for key in ("detail", "message", "error", "msg"):
            v = data.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()[:300]
            if isinstance(v, list):
                parts = []
                for item in v:
                    if isinstance(item, dict):
                        loc = ".".join(str(x) for x in (item.get("loc") or []) if x != "body")
                        parts.append(f"{loc}: {item.get('msg') or ''}".strip(": "))
                    else:
                        parts.append(str(item))
                return "; ".join(p for p in parts if p)[:300]
    return str(data)[:300]


def _classify(status: int) -> ErrorKind:
    if status >= 500 or status in (408, 425, 429):
        return ErrorKind.TRANSIENT
    return ErrorKind.PERMANENT


def as_rows(data, *keys: str) -> list[dict]:
    """List of dict rows from a panel list response: a bare list, or an object wrapping the list under one of ``keys``."""
    if isinstance(data, dict):
        for key in keys:
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            return []
    return [row for row in (data or []) if isinstance(row, dict)] if isinstance(data, list) else []


def iso_expire(at: dt.datetime | None) -> str | int:
    if not at:
        return 0
    at = at if at.tzinfo else at.replace(tzinfo=dt.UTC)
    return at.astimezone(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_expire(v) -> dt.datetime | None:
    if v in (None, 0, "0", ""):
        return None
    if isinstance(v, int | float):
        return dt.datetime.fromtimestamp(v, dt.UTC)
    d = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=dt.UTC)


class PasarGuardCore:
    kind = "pasarguard"

    def __init__(
        self,
        base_url: str,
        credentials: dict,
        config: dict | None = None,
        timeout: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        base = (base_url or "").strip().rstrip("/")
        parts = urlsplit(base)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise PanelError(ErrorKind.PERMANENT, "pasarguard: invalid base_url")
        # Dashboard paths (/dashboard) are not the API root.
        if parts.path.rstrip("/").endswith("/dashboard"):
            base = base[: -len("/dashboard")]
        self.base = base
        self.creds = credentials or {}
        self.cfg = config or {}
        self.timeout = float(timeout or self.cfg.get("timeout") or 20)
        self.transport = transport
        self.legacy = self.cfg.get("api_style") == "legacy"
        self._key = (self.base, str(self.creds.get("username") or "token"))

    # ------------------------------------------------------------------ transport
    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base,
            timeout=self.timeout,
            follow_redirects=False,
            verify=self.cfg.get("verify_tls", True),
            transport=self.transport,
        )

    async def _login(self, c: httpx.AsyncClient) -> str:
        if self.creds.get("access_token") and not self.creds.get("username"):
            return self.creds["access_token"]
        user, pwd = (self.creds.get("username") or "").strip(), (self.creds.get("password") or "").replace("\r", "").strip()
        if not user or not pwd:
            raise PanelError(ErrorKind.PERMANENT, "pasarguard: credentials missing")
        last = None
        for data in ({"grant_type": "password", "username": user, "password": pwd}, {"username": user, "password": pwd}):
            last = await c.post("/api/admin/token", data=data)
            if last.status_code < 400:
                token = (last.json() or {}).get("access_token")
                if not token:
                    raise PanelError(ErrorKind.PERMANENT, "pasarguard: login response missing access_token")
                _TOKENS[self._key] = (token, time.monotonic() + _TOKEN_TTL)
                return token
            if last.status_code in (401, 403):
                raise PanelError(ErrorKind.PERMANENT, f"pasarguard: login failed ({last.status_code})")
            if last.status_code != 422:  # 422 => retry without grant_type
                break
        raise PanelError(_classify(last.status_code), f"pasarguard: login http {last.status_code}: {_error_detail(last.text)}")

    def _uses_api_key(self) -> bool:
        return bool(self.creds.get("api_key"))

    async def _auth_headers(self, c: httpx.AsyncClient, *, fresh: bool = False) -> dict[str, str]:
        if self._uses_api_key():
            return {"X-Api-Key": str(self.creds["api_key"])}
        token = await self._token(c, fresh=fresh)
        return {"Authorization": f"Bearer {token}"}

    async def _token(self, c: httpx.AsyncClient, *, fresh: bool = False) -> str:
        cached = _TOKENS.get(self._key)
        if cached and not fresh and cached[1] > time.monotonic():
            return cached[0]
        return await self._login(c)

    async def _req(self, method: str, path: str, *, ok404: bool = False, ok409: bool = False, **kw):
        async with self._client() as c:
            try:
                headers = await self._auth_headers(c)
                r = await c.request(method, path, headers=headers, **kw)
                if r.status_code == 401 and not self._uses_api_key():
                    _TOKENS.pop(self._key, None)
                    headers = await self._auth_headers(c, fresh=True)
                    r = await c.request(method, path, headers=headers, **kw)
            except httpx.TimeoutException as e:
                # Outcome unknown (the panel may have applied it): caller must re-read state before retrying.
                raise PanelError(ErrorKind.UNKNOWN, f"pasarguard timeout: {e}") from e
            except httpx.HTTPError as e:
                raise PanelError(ErrorKind.TRANSIENT, f"pasarguard network: {e}") from e
        if ok404 and r.status_code == 404:
            return None
        if ok409 and r.status_code == 409:
            return {"__conflict__": True}
        if 300 <= r.status_code < 400:
            raise PanelError(ErrorKind.PERMANENT, f"pasarguard: unexpected redirect {r.status_code} (check base_url)")
        if r.status_code >= 400:
            raise PanelError(_classify(r.status_code), f"pasarguard {method} {path} -> {r.status_code}: {_error_detail(r.text)}")
        if r.status_code == 204 or not r.content:
            return {}
        try:
            return r.json()
        except ValueError as e:
            raise PanelError(ErrorKind.PERMANENT, "pasarguard: non-JSON response (is base_url the API root?)") from e

    # ------------------------------------------------------------------ health
    async def health_check(self) -> bool:
        for path in ("/api/system", "/api/admin"):
            try:
                await self._req("GET", path)
                return True
            except PanelError as e:
                if "-> 403" in e.message or "-> 404" in e.message:
                    continue  # limited role / older build: try the next probe
                return False
        return False

    async def close(self) -> None:
        return None
