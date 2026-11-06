"""PasarGuard panel adapter (https://github.com/PasarGuard/panel).

API contract aligned with the production client in PGClockBot (app/services/pasarguard.py)
and the current PasarGuard panel API:
- auth:    POST /api/admin/token (form, grant_type=password) -> {"access_token": ...}; Bearer afterwards
- read:    GET  /api/user/by-username/{username}
- create:  POST /api/user   {username, status, group_ids, proxy_settings, data_limit, expire, hwid_limit, note}
- template create: POST /api/user/from_template {user_template_id, username, note}
- modify:  PUT  /api/user/by-id/{id}
- delete:  DELETE /api/user/by-id/{id}
- reset:   POST /api/user/by-id/{id}/reset          (traffic reset)
- rotate:  POST /api/user/by-id/{id}/revoke_sub     (new subscription link)
- owner:   PUT  /api/user/by-id/{id}/set_owner?admin_username=   (the account belongs to the store's admin)
- admins:  GET /api/admins?username=, POST /api/admin, PUT /api/admin/by-id/{id}, GET /api/admin-roles/simple
- health:  GET  /api/system  (fallback GET /api/admin, which needs no admins.read)
`expire` is sent as ISO-8601 UTC ("...Z"), 0 = never. `data_limit` bytes, 0 = unlimited.
Redirects are never followed with a Bearer token (credential forwarding / SSRF).

Panel.config (the destination keys below may also come from ``Server.target``, which wins; see vpn.targets):
  {"group_ids": [1, 2],            # REQUIRED by current PasarGuard UserCreate (or "user_template_id" instead)
   "limits_from": "product"|"template",  # template mode only: product (default) re-applies the package volume/time after creation
   "api_style": "current"|"legacy", # legacy = Marzban-style /api/user/{username} (old PasarGuard builds)
   "sub_base_url": "https://sub.example.com",  # prefix for relative subscription_url
   "verify_tls": true, "timeout": 20, "username_prefix": ""}
Panel credentials (encrypted): {"username": "...", "password": "..."},
{"access_token": "..."} or {"api_key": "..."}.
"""

import datetime as dt
import json
import time
from urllib.parse import quote, urlsplit

import httpx

from melorin.modules.vpn.adapters.base import AccountSpec, Capabilities, ErrorKind, PanelAccount, PanelError

_STATUS = {"active": "active", "disabled": "disabled", "expired": "expired", "limited": "limited", "on_hold": "active"}
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


def build_create_payload(spec: AccountSpec, cfg: dict) -> dict:
    template_id = cfg.get("user_template_id")
    if template_id is not None:
        try:
            template_id = int(template_id)
        except (TypeError, ValueError) as exc:
            raise PanelError(ErrorKind.PERMANENT, "pasarguard: config.user_template_id must be an integer") from exc
        if template_id <= 0:
            raise PanelError(ErrorKind.PERMANENT, "pasarguard: config.user_template_id must be positive")
        body = {"user_template_id": template_id, "username": spec.username}
        if spec.note:
            body["note"] = spec.note[:500]
        return body
    group_ids = [int(g) for g in (cfg.get("group_ids") or [])]
    if not group_ids:
        raise PanelError(ErrorKind.PERMANENT, "pasarguard: config.group_ids is required")
    body: dict = {
        "username": spec.username,
        "status": "active",
        "group_ids": group_ids,
        "proxy_settings": cfg.get("proxy_settings") or {},
        "data_limit": int(spec.traffic_bytes or 0),
        "expire": iso_expire(spec.expire_at),
    }
    if spec.max_devices and int(spec.max_devices) > 0:
        body["hwid_limit"] = int(spec.max_devices)
    if spec.note:
        body["note"] = spec.note[:500]
    if cfg.get("data_limit_reset_strategy"):
        body["data_limit_reset_strategy"] = cfg["data_limit_reset_strategy"]
    return body


def build_modify_payload(
    *, expire_at: dt.datetime | None = None, traffic_bytes: int | None = None, status: str | None = None, set_expire: bool = False
) -> dict:
    body: dict = {}
    if set_expire:
        body["expire"] = iso_expire(expire_at)
    if traffic_bytes is not None:
        body["data_limit"] = int(traffic_bytes)
    if status:
        body["status"] = status
    return body


class PasarGuardAdapter:
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

    # ------------------------------------------------------------------ paths
    @staticmethod
    def _q(username: str) -> str:
        return quote(username, safe="")

    def _read_path(self, username: str) -> str:
        return f"/api/user/{self._q(username)}" if self.legacy else f"/api/user/by-username/{self._q(username)}"

    def _write_path(self, d: dict, suffix: str = "") -> str:
        if self.legacy or d.get("id") is None:
            return f"/api/user/{self._q(d['username'])}{suffix}"
        return f"/api/user/by-id/{int(d['id'])}{suffix}"

    async def _get_raw(self, username: str) -> dict | None:
        d = await self._req("GET", self._read_path(username), ok404=True)
        return d or None

    async def _require(self, username: str) -> dict:
        d = await self._get_raw(username)
        if not d:
            raise PanelError(ErrorKind.PERMANENT, f"pasarguard: user {username} not found")
        return d

    # ------------------------------------------------------------------ mapping
    def _to_account(self, d: dict) -> PanelAccount:
        sub = d.get("subscription_url")
        if sub and sub.startswith("/"):
            sub = (self.cfg.get("sub_base_url") or self.base).rstrip("/") + sub
        links = d.get("links") or []
        return PanelAccount(
            ref=str(d.get("id") if d.get("id") is not None else d["username"]),
            username=d["username"],
            status=self.normalize_status(str(d.get("status") or "")),
            expire_at=parse_expire(d.get("expire")),
            traffic_limit_bytes=int(d.get("data_limit") or 0),
            traffic_used_bytes=int(d.get("used_traffic") or 0),
            subscription_url=sub,
            links=list(links) if isinstance(links, list) else [],
        )

    # ------------------------------------------------------------------ PanelAdapter
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

    def capabilities(self) -> Capabilities:
        return Capabilities(suspend=True, extend=True, subscription_url=True, traffic_reset=True)

    def _template_mode(self) -> bool:
        return self.cfg.get("user_template_id") is not None

    def _product_limits(self) -> bool:
        """A template carries its own volume/time. By default the PACKAGE wins (``limits_from=product``), so one template can
        serve every plan; ``limits_from=template`` keeps whatever the template says."""
        return self._template_mode() and self.cfg.get("limits_from", "product") == "product"

    @staticmethod
    def _limits_match(d: dict, spec: AccountSpec) -> bool:
        want_exp = parse_expire(iso_expire(spec.expire_at))
        have_exp = parse_expire(d.get("expire"))
        same_exp = (want_exp is None and have_exp is None) or (
            want_exp is not None and have_exp is not None and abs((want_exp - have_exp).total_seconds()) < 2
        )
        return same_exp and int(d.get("data_limit") or 0) == int(spec.traffic_bytes or 0)

    async def _apply_product_limits(self, d: dict, spec: AccountSpec) -> dict:
        """Step 2 of template creation: overwrite the template's volume/time with the package's (absolute values: safe to repeat)."""
        if self._limits_match(d, spec):
            return d
        out = await self._req(
            "PUT",
            self._write_path(d),
            json=build_modify_payload(expire_at=spec.expire_at, traffic_bytes=spec.traffic_bytes, set_expire=True),
        )
        return out if isinstance(out, dict) and out.get("username") else await self._require(spec.username)

    @staticmethod
    def _owner_of(d: dict) -> str | None:
        admin = d.get("admin")
        return admin.get("username") if isinstance(admin, dict) else None

    async def _ensure_owner(self, d: dict, owner: str | None) -> dict:
        """Make ``owner`` (a panel admin) the owner of user ``d``. Idempotent; a failure is TRANSIENT so the order retries and the
        account is never left under the wrong admin silently."""
        if not owner or self._owner_of(d) == owner:
            return d
        try:
            out = await self._req(
                "PUT",
                self._write_path(d, "/set_owner"),
                params={"admin_username": owner},
            )
        except PanelError as e:
            raise PanelError(ErrorKind.TRANSIENT, f"pasarguard: set owner {owner}: {e.message}") from e
        return out if isinstance(out, dict) and out.get("username") else await self._require(d["username"])

    async def create_account(self, spec: AccountSpec) -> PanelAccount:
        existing = await self._get_raw(spec.username)
        if existing:  # idempotent retry after an UNKNOWN outcome
            if self._product_limits():  # the previous attempt may have died between create and the limits step
                existing = await self._apply_product_limits(existing, spec)
            return self._to_account(await self._ensure_owner(existing, spec.owner))
        endpoint = "/api/user/from_template" if self._template_mode() else "/api/user"
        d = await self._req("POST", endpoint, json=build_create_payload(spec, self.cfg), ok409=True)
        if d.get("__conflict__"):
            d = await self._require(spec.username)
        elif not d.get("username"):
            d = await self._require(spec.username)
        if self._product_limits():
            d = await self._apply_product_limits(d, spec)
        d = await self._ensure_owner(d, spec.owner)
        return self._to_account(d)

    async def get_account(self, username: str) -> PanelAccount | None:
        d = await self._get_raw(username)
        return self._to_account(d) if d else None

    async def suspend_account(self, username: str) -> None:
        d = await self._require(username)
        await self._req("PUT", self._write_path(d), json=build_modify_payload(status="disabled"))

    async def resume_account(self, username: str) -> None:
        d = await self._require(username)
        await self._req("PUT", self._write_path(d), json=build_modify_payload(status="active"))

    async def extend_account(self, username: str, *, expire_at: dt.datetime | None, traffic_bytes: int) -> PanelAccount:
        d = await self._require(username)
        out = await self._req(
            "PUT",
            self._write_path(d),
            json=build_modify_payload(expire_at=expire_at, traffic_bytes=traffic_bytes, status="active", set_expire=True),
        )
        return self._to_account(out if out.get("username") else await self._require(username))

    async def revoke_account(self, username: str) -> None:
        d = await self._get_raw(username)
        if not d:
            return  # already gone: idempotent
        await self._req("DELETE", self._write_path(d), ok404=True)

    async def reset_traffic(self, username: str) -> PanelAccount:
        d = await self._require(username)
        out = await self._req("POST", self._write_path(d, "/reset"))
        return self._to_account(out if out.get("username") else await self._require(username))

    async def rotate_subscription(self, username: str) -> PanelAccount:
        d = await self._require(username)
        out = await self._req("POST", self._write_path(d, "/revoke_sub"))
        return self._to_account(out if out.get("username") else await self._require(username))

    # ------------------------------------------------------------------ admins (one Operator per store)
    async def _role_id(self, name: str) -> int:
        data = await self._req("GET", "/api/admin-roles/simple")
        roles = data.get("roles") if isinstance(data, dict) else data
        for r in roles or []:
            if isinstance(r, dict) and str(r.get("name", "")).strip().lower() == name.strip().lower() and not r.get("is_owner"):
                return int(r["id"])
        raise PanelError(ErrorKind.PERMANENT, f"pasarguard: admin role '{name}' not found")

    async def find_admin(self, username: str) -> dict | None:
        data = await self._req("GET", "/api/admins", params={"username": username, "limit": 20})
        for a in (data.get("admins") if isinstance(data, dict) else data) or []:
            if isinstance(a, dict) and a.get("username") == username:
                return a
        return None

    @staticmethod
    def _profile_body(profile: dict | None) -> dict:
        """Only the 'Profile & contact' fields; empty string clears a text field, ``None`` leaves it alone."""
        body: dict = {}
        for key in ("profile_title", "support_url", "discord_webhook", "sub_domain", "note"):
            if profile and profile.get(key) is not None:
                body[key] = str(profile[key])
        if profile and profile.get("telegram_id") not in (None, "", 0):
            body["telegram_id"] = int(profile["telegram_id"])
        return body

    async def ensure_admin(self, username: str, password: str, *, role: str = "operator", profile: dict | None = None) -> dict:
        """Create the admin when missing (role Operator), adopt it (and set our password) when it already exists. Idempotent."""
        existing = await self.find_admin(username)
        if existing:
            await self._req("PUT", f"/api/admin/by-id/{int(existing['id'])}", json={"password": password, **self._profile_body(profile)})
            return existing
        body = {"username": username, "password": password, "role_id": await self._role_id(role), **self._profile_body(profile)}
        out = await self._req("POST", "/api/admin", json=body, ok409=True)
        if out.get("__conflict__"):  # lost a race, or the Telegram id belongs to another admin
            found = await self.find_admin(username)
            if not found:
                body.pop("telegram_id", None)
                out = await self._req("POST", "/api/admin", json=body)
                return out
            return found
        return out

    async def update_admin_profile(self, remote_id: int, profile: dict, *, password: str | None = None) -> dict:
        body = self._profile_body(profile)
        if password:
            body["password"] = password
        if not body:
            return {}
        return await self._req("PUT", f"/api/admin/by-id/{int(remote_id)}", json=body)

    async def bulk_set_owner(self, refs: list[str], owner: str) -> int:
        """Move existing users (panel ids) under ``owner``; chunked, idempotent."""
        ids = [int(r) for r in refs if str(r).isdigit()]
        for i in range(0, len(ids), 200):
            await self._req("PUT", "/api/users/bulk/set_owner", json={"ids": ids[i : i + 200], "admin_username": owner})
        return len(ids)

    async def list_groups(self) -> list[dict]:
        """Admin helper to pick group_ids."""
        data = await self._req("GET", "/api/groups/simple", ok404=True)
        if data is None:
            data = await self._req("GET", "/api/groups")
        if isinstance(data, dict):
            data = data.get("groups") or []
        return [g for g in data if isinstance(g, dict)]

    async def list_templates(self) -> list[dict]:
        """Admin helper to pick user_template_id (ready-made user settings: groups + volume + time)."""
        data = await self._req("GET", "/api/user_templates", ok404=True)
        if isinstance(data, dict):
            data = data.get("user_templates") or data.get("templates") or []
        return [t for t in (data or []) if isinstance(t, dict)]

    async def list_targets(self) -> dict:
        """Everything an admin can aim a server at: ``{"groups": [...], "templates": [...]}`` in a flat, UI-ready shape."""
        groups = [
            {"id": int(g["id"]), "name": str(g.get("name") or g["id"]), "disabled": bool(g.get("is_disabled", False))}
            for g in await self.list_groups()
            if g.get("id") is not None
        ]
        try:
            templates = [
                {
                    "id": int(t["id"]),
                    "name": str(t.get("name") or t["id"]),
                    "data_limit": int(t.get("data_limit") or 0),
                    "expire_duration": int(t.get("expire_duration") or 0),
                    "group_ids": [int(g) for g in (t.get("group_ids") or [])],
                    "disabled": bool(t.get("is_disabled", False)),
                }
                for t in await self.list_templates()
                if t.get("id") is not None
            ]
        except PanelError:
            templates = []  # an older build or a role without template access: groups still work
        return {"kind": "pasarguard", "groups": groups, "templates": templates}

    def normalize_status(self, raw: str) -> str:
        return _STATUS.get(raw, "unknown")

    async def close(self) -> None:
        return None
