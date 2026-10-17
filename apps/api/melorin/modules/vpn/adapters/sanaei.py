"""Sanaei 3x-ui adapter (https://github.com/MHSanaei/3x-ui, API reference: https://docs.sanaei.dev/docs/reference/api/).

Two API generations are supported:

* ``v3`` (3x-ui 3.x): clients are first-class rows under ``/panel/api/clients/*`` and can be attached
  to several inbounds at once.
    - read:    GET  /panel/api/clients/get/{email}      -> obj = {"client": {...}, "inboundIds": [...]}
                    (not found = HTTP 200 + success=false + msg "record not found")
    - traffic: GET  /panel/api/clients/traffic/{email}  -> obj = {up, down, total, expiryTime, enable, ...}
    - links:   GET  /panel/api/clients/links/{email}    -> obj = ["vless://...", ...]
    - create:  POST /panel/api/clients/add              {"client": {...}, "inboundIds": [...]}
               (per-protocol secrets are generated server-side when omitted)
    - update:  POST /panel/api/clients/update/{email}   full row replace (NOT a patch): read -> merge -> write
    - delete:  POST /panel/api/clients/del/{email}
    - reset:   POST /panel/api/clients/resetTraffic/{email}
    - health:  GET  /panel/api/server/status
* ``legacy`` (3x-ui 1.x/2.x): clients live inside ``inbound.settings.clients``.
    - GET /panel/api/inbounds/get/{id}, POST /panel/api/inbounds/addClient,
      POST /panel/api/inbounds/updateClient/{clientId}, POST /panel/api/inbounds/{id}/delClient/{clientId},
      POST /panel/api/inbounds/{id}/resetClientTraffic/{email}, POST /server/status

``api_style="auto"`` (default) probes ``/panel/api/clients/*`` once and falls back to legacy on 404.

Auth: ``Authorization: Bearer <api_token>`` (Settings -> Security -> API Token; preferred, no session,
no CSRF) or cookie session from ``POST {base}/login``. The panel answers unauthenticated requests with
404 (401 when ``X-Requested-With: XMLHttpRequest`` is sent, which we always send), so a 401 means
"session expired" and a 404 means "route does not exist".

base_url must include the panel web base path (e.g. ``https://panel.example.com:2053/kharej``).
Redirects are never followed with credentials (credential forwarding / SSRF).

Panel.config:
  {"api_style": "auto" | "v3" | "legacy",
   "inbound_ids": [1, 2],                 # or legacy "inbound_id": 1
   "template_username": "template",       # optional: copy inboundIds/flow/limitIp from a manually-made client
   "sub_base_url": "https://sub.example.com:2096/sub",   # REQUIRED: Sub Port + Sub Path, subId is appended
   "flow": "",                            # e.g. "xtls-rprx-vision"
   "limit_ip": 0,                         # default device/IP limit when AccountSpec.max_devices is empty
   "fetch_links": true, "verify_tls": true, "timeout": 15}
Panel credentials (encrypted): {"api_token": "..."} or {"username": "...", "password": "..."}
"""

import datetime as dt
import json
import secrets
import time
import uuid
from urllib.parse import quote, urlsplit

import httpx

from melorin.modules.vpn.adapters.base import AccountSpec, Capabilities, ErrorKind, PanelAccount, PanelError

_NOT_FOUND_MARKERS = ("record not found", "not found", "client not found", "no such client")
_TEMPLATE_TTL = 300
# Fields of 3x-ui's model.Client. /clients/update binds into this struct, so anything else
# (numeric record id, createdAt, inboundIds, traffic, ...) must not be sent back.
_CLIENT_FIELDS = (
    "id",
    "password",
    "auth",
    "security",
    "flow",
    "email",
    "limitIp",
    "limitHwid",
    "totalGB",
    "expiryTime",
    "enable",
    "tgId",
    "subId",
    "comment",
    "reset",
    "reverse",
    "group",
    "groupId",
)


def _classify(status: int) -> ErrorKind:
    if status >= 500 or status in (408, 425, 429):
        return ErrorKind.TRANSIENT
    return ErrorKind.PERMANENT


def _is_not_found(data: dict) -> bool:
    msg = str(data.get("msg") or "").lower()
    return data.get("success") is False and not data.get("obj") and any(m in msg for m in _NOT_FOUND_MARKERS)


def to_ms(at: dt.datetime | None) -> int:
    if not at:
        return 0
    at = at if at.tzinfo else at.replace(tzinfo=dt.UTC)
    return int(at.timestamp() * 1000)


def from_ms(v) -> dt.datetime | None:
    try:
        v = int(v or 0)
    except (TypeError, ValueError):
        return None
    # Negative expiryTime = "starts on first use" (delayed start); no absolute date yet.
    return dt.datetime.fromtimestamp(v / 1000, dt.UTC) if v > 0 else None


def _int(v, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _settings(inbound: dict) -> dict:
    """3x-ui 3.x returns settings as a nested object, 2.x as a JSON-encoded string."""
    raw = inbound.get("settings")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except ValueError as e:
            raise PanelError(ErrorKind.PERMANENT, f"sanaei: inbound settings is not valid JSON: {e}") from e
    return {}


def clean_client(rec: dict) -> dict:
    """Turn a v3 ClientRecord (numeric id + uuid) into a model.Client payload (id = uuid string)."""
    out = {k: rec[k] for k in _CLIENT_FIELDS if k in rec and k != "id"}
    rid = rec.get("uuid") or (rec.get("id") if isinstance(rec.get("id"), str) else None)
    if rid:
        out["id"] = rid
    # model.Client.tgId is int64: sending "" fails with "cannot unmarshal string ... tgId of type int64".
    out["tgId"] = _int(rec.get("tgId"), 0)
    return out


class SanaeiAdapter:
    kind = "sanaei"

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
            raise PanelError(ErrorKind.PERMANENT, "sanaei: invalid base_url")
        # Admins often paste the dashboard URL; the API root is the web base path.
        for suffix in ("/panel/inbounds", "/panel"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        self.base = base
        self.creds = credentials or {}
        self.cfg = config or {}
        self.timeout = float(timeout or self.cfg.get("timeout") or 15)
        self.transport = transport
        style = str(self.cfg.get("api_style") or "auto").lower()
        if style not in ("auto", "v3", "legacy"):
            raise PanelError(ErrorKind.PERMANENT, "sanaei: config.api_style must be auto, v3 or legacy")
        self._style: str | None = None if style == "auto" else style
        self._client: httpx.AsyncClient | None = None
        self._logged_in = False
        self._template: tuple[dict, float] | None = None

    # ------------------------------------------------------------------ config helpers
    @property
    def token(self) -> str | None:
        t = (self.creds.get("api_token") or self.creds.get("token") or "").strip()
        return t or None

    @property
    def inbound_ids(self) -> list[int]:
        ids = self.cfg.get("inbound_ids")
        if ids is None and self.cfg.get("inbound_id") is not None:
            ids = [self.cfg["inbound_id"]]
        return [int(i) for i in (ids or [])]

    @property
    def inbound_id(self) -> int:  # backwards compatibility with the previous single-inbound adapter
        return (self.inbound_ids or [1])[0]

    def _sub(self, sub_id: str | None) -> str | None:
        b = (self.cfg.get("sub_base_url") or "").strip()
        return f"{b.rstrip('/')}/{sub_id}" if b and sub_id else None

    def _require_sub_base(self) -> None:
        # Fail before writing: otherwise the client is created on the panel but the order rolls back
        # with no deliverable link, leaving an orphan on 3x-ui.
        if not (self.cfg.get("sub_base_url") or "").strip():
            raise PanelError(
                ErrorKind.PERMANENT,
                "sanaei: config.sub_base_url is required (Settings -> Subscription: Sub Port + Sub Path, "
                "e.g. https://sub.example.com:2096/sub)",
            )

    @staticmethod
    def _q(v: str) -> str:
        return quote(str(v), safe="")

    # ------------------------------------------------------------------ transport
    async def _c(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            self._client = httpx.AsyncClient(
                base_url=self.base,
                timeout=self.timeout,
                follow_redirects=False,
                headers=headers,
                verify=self.cfg.get("verify_tls", True),
                transport=self.transport,
            )
        if not self.token and not self._logged_in:
            await self._login()
        return self._client

    async def _login(self) -> None:
        user, pwd = (self.creds.get("username") or "").strip(), self.creds.get("password") or ""
        if not user or not pwd:
            raise PanelError(ErrorKind.PERMANENT, "sanaei: credentials missing (api_token or username/password)")
        try:
            r = await self._client.post("/login", data={"username": user, "password": pwd})
        except httpx.TimeoutException as e:
            raise PanelError(ErrorKind.TRANSIENT, f"sanaei: login timeout: {e}") from e
        except httpx.HTTPError as e:
            raise PanelError(ErrorKind.TRANSIENT, f"sanaei: login network error: {e}") from e
        if r.status_code in (301, 302, 303, 307, 308):
            raise PanelError(ErrorKind.PERMANENT, "sanaei: login redirected; check base_url (scheme / web base path)")
        if r.status_code == 404:
            raise PanelError(ErrorKind.PERMANENT, "sanaei: /login not found; base_url must include the panel web base path")
        if r.status_code != 200:
            raise PanelError(_classify(r.status_code), f"sanaei: login http {r.status_code}")
        try:
            ok = bool(r.json().get("success"))
        except ValueError:
            ok = False
        if not ok:
            raise PanelError(ErrorKind.PERMANENT, "sanaei: panel login failed (wrong credentials or 2FA enabled; use an API token)")
        self._logged_in = True

    async def _raw(self, method: str, path: str, **kw) -> httpx.Response:
        c = await self._c()
        try:
            r = await c.request(method, path, **kw)
            if r.status_code == 401 and not self.token:  # cookie session expired
                self._logged_in = False
                await self._login()
                r = await c.request(method, path, **kw)
        except httpx.TimeoutException as e:
            # Outcome of a write is unknown: caller must read back before retrying.
            raise PanelError(ErrorKind.UNKNOWN, f"sanaei: timeout on {path}: {e}") from e
        except httpx.HTTPError as e:
            raise PanelError(ErrorKind.TRANSIENT, f"sanaei: network error on {path}: {e}") from e
        return r

    async def _req(self, method: str, path: str, *, ok_missing: bool = False, **kw) -> dict | None:
        r = await self._raw(method, path, **kw)
        if r.status_code in (301, 302, 303, 307, 308):
            raise PanelError(ErrorKind.PERMANENT, f"sanaei: unexpected redirect on {path}; check base_url")
        if r.status_code == 401:
            raise PanelError(ErrorKind.PERMANENT, "sanaei: unauthorized (invalid API token or credentials)")
        if r.status_code != 200:
            raise PanelError(_classify(r.status_code), f"sanaei: http {r.status_code} on {path}")
        try:
            data = r.json()
        except ValueError as e:
            raise PanelError(ErrorKind.PERMANENT, f"sanaei: non-JSON response on {path} (wrong base_url?)") from e
        if not isinstance(data, dict):
            raise PanelError(ErrorKind.PERMANENT, f"sanaei: unexpected response on {path}")
        if data.get("success") is False:
            if ok_missing and _is_not_found(data):
                return None
            raise PanelError(ErrorKind.PERMANENT, f"sanaei: {str(data.get('msg') or 'panel error')[:300]}")
        return data

    async def _api_style(self) -> str:
        if self._style:
            return self._style
        r = await self._raw("GET", "/panel/api/clients/list/paged", params={"page": 1, "pageSize": 1})
        if r.status_code == 404:
            self._style = "legacy"
        elif r.status_code == 200:
            self._style = "v3"
        elif r.status_code == 401:
            raise PanelError(ErrorKind.PERMANENT, "sanaei: unauthorized (invalid API token or credentials)")
        else:
            raise PanelError(_classify(r.status_code), f"sanaei: api probe http {r.status_code}")
        return self._style

    # ------------------------------------------------------------------ status helpers
    def _to_account(self, c: dict, traffic: dict, ref: str, links: list[str] | None = None) -> PanelAccount:
        expire_at = from_ms(c.get("expiryTime", traffic.get("expiryTime")))
        total = _int(c.get("totalGB", traffic.get("total")), 0)
        used = max(0, _int(traffic.get("up")) + _int(traffic.get("down")))
        enabled = bool(c.get("enable", True)) and traffic.get("enable", True) is not False
        if expire_at and expire_at <= dt.datetime.now(dt.UTC):
            status = "expired"
        elif total and used >= total:
            status = "limited"
        elif not enabled:
            status = "disabled"
        else:
            status = "active"
        sub_id = c.get("subId") or traffic.get("subId")
        return PanelAccount(
            ref=ref,
            username=c.get("email") or traffic.get("email") or "",
            status=status,
            expire_at=expire_at,
            traffic_limit_bytes=total,
            traffic_used_bytes=used,
            subscription_url=self._sub(sub_id),
            links=links or [],
        )

    async def _links(self, email: str) -> list[str]:
        if not self.cfg.get("fetch_links", True):
            return []
        try:
            d = await self._req("GET", f"/panel/api/clients/links/{self._q(email)}", ok_missing=True)
        except PanelError:
            return []  # links are cosmetic; subscription URL is the deliverable
        obj = (d or {}).get("obj")
        return [x for x in obj if isinstance(x, str)] if isinstance(obj, list) else []

    # ------------------------------------------------------------------ v3 helpers
    async def _v3_get(self, email: str) -> tuple[dict, list[int]] | None:
        d = await self._req("GET", f"/panel/api/clients/get/{self._q(email)}", ok_missing=True)
        obj = (d or {}).get("obj")
        if not obj:
            return None
        if isinstance(obj, dict) and isinstance(obj.get("client"), dict):
            return obj["client"], [int(i) for i in obj.get("inboundIds") or []]
        if isinstance(obj, dict) and obj.get("email"):  # flat shape (some 3.0.x builds)
            return obj, [int(i) for i in obj.get("inboundIds") or []]
        raise PanelError(ErrorKind.PERMANENT, "sanaei: unexpected client payload")

    async def _v3_traffic(self, email: str, rec: dict) -> dict:
        try:
            d = await self._req("GET", f"/panel/api/clients/traffic/{self._q(email)}", ok_missing=True)
        except PanelError:
            d = None
        obj = (d or {}).get("obj")
        if isinstance(obj, dict):
            return obj
        return rec.get("traffic") if isinstance(rec.get("traffic"), dict) else {}

    async def _template_defaults(self) -> dict:
        """inboundIds/flow/limitIp from config, optionally copied from a manually created template client."""
        name = (self.cfg.get("template_username") or "").strip()
        if not name:
            return {"inboundIds": self.inbound_ids, "flow": self.cfg.get("flow", ""), "limitIp": _int(self.cfg.get("limit_ip"), 0)}
        if self._template and self._template[1] > time.monotonic():
            return self._template[0]
        found = await self._v3_get(name)
        if not found:  # never cache a miss
            raise PanelError(ErrorKind.PERMANENT, f"sanaei: template client '{name}' not found on panel")
        rec, ids = found
        tpl = {
            "inboundIds": self.inbound_ids or ids,
            "flow": self.cfg.get("flow", rec.get("flow") or ""),
            "limitIp": _int(self.cfg.get("limit_ip", rec.get("limitIp")), 0),
        }
        self._template = (tpl, time.monotonic() + _TEMPLATE_TTL)
        return tpl

    async def _v3_update(self, email: str, **changes) -> dict:
        found = await self._v3_get(email)
        if not found:
            raise PanelError(ErrorKind.PERMANENT, "sanaei: client not found on panel")
        body = clean_client(found[0])
        body.update(changes)
        body["email"] = email
        await self._req("POST", f"/panel/api/clients/update/{self._q(email)}", json=body)
        return body

    # ------------------------------------------------------------------ legacy helpers
    def _legacy_client_obj(self, spec: AccountSpec, tpl: dict) -> dict:
        return {
            "id": str(uuid.uuid4()),
            "password": secrets.token_urlsafe(12),
            "email": spec.username,
            "enable": True,
            "flow": tpl.get("flow", ""),
            "limitIp": _int(spec.max_devices or tpl.get("limitIp"), 0),
            "totalGB": int(spec.traffic_bytes or 0),
            "expiryTime": to_ms(spec.expire_at),
            "subId": secrets.token_hex(8),
            "tgId": 0,
            "reset": 0,
            "comment": (spec.note or "")[:200],
        }

    async def _legacy_find(self, email: str) -> tuple[int, dict, dict] | None:
        for iid in self.inbound_ids or [1]:
            d = await self._req("GET", f"/panel/api/inbounds/get/{iid}", ok_missing=True)
            inbound = (d or {}).get("obj") or {}
            if not inbound:
                continue
            stats = {s.get("email"): s for s in inbound.get("clientStats") or []}
            for c in _settings(inbound).get("clients", []) or []:
                if c.get("email") == email:
                    return iid, c, stats.get(email, {})
        return None

    @staticmethod
    def _legacy_cid(c: dict) -> str:
        # vless/vmess key on "id", trojan on "password", shadowsocks on "email".
        return str(c.get("id") or c.get("password") or c.get("email"))

    async def _legacy_update(self, email: str, **changes) -> None:
        found = await self._legacy_find(email)
        if not found:
            raise PanelError(ErrorKind.PERMANENT, "sanaei: client not found on panel")
        iid, c, _ = found
        c.update(changes)
        c["tgId"] = _int(c.get("tgId"), 0)
        await self._req(
            "POST",
            f"/panel/api/inbounds/updateClient/{self._q(self._legacy_cid(c))}",
            json={"id": iid, "settings": json.dumps({"clients": [c]})},
        )

    # ------------------------------------------------------------------ PanelAdapter
    async def health_check(self) -> bool:
        try:
            style = await self._api_style()
            if style == "v3":
                await self._req("GET", "/panel/api/server/status")
            else:
                try:
                    await self._req("GET", "/panel/api/server/status")
                except PanelError:
                    await self._req("POST", "/server/status")
            return True
        except PanelError:
            return False

    async def server_status(self) -> dict:
        d = await self._req("GET", "/panel/api/server/status")
        return (d or {}).get("obj") or {}

    def capabilities(self) -> Capabilities:
        return Capabilities(suspend=True, extend=True, subscription_url=True, traffic_reset=True)

    async def create_account(self, spec: AccountSpec) -> PanelAccount:
        self._require_sub_base()
        existing = await self.get_account(spec.username)
        if existing:  # idempotent create (retry after UNKNOWN timeout)
            return existing
        if await self._api_style() == "v3":
            tpl = await self._template_defaults()
            if not tpl["inboundIds"]:
                raise PanelError(ErrorKind.PERMANENT, "sanaei: no inbound configured (config.inbound_ids or template_username)")
            sub_id = secrets.token_hex(8)
            client = {
                "email": spec.username,
                "enable": True,
                "totalGB": int(spec.traffic_bytes or 0),
                "expiryTime": to_ms(spec.expire_at),
                "limitIp": _int(spec.max_devices or tpl.get("limitIp"), 0),
                "tgId": 0,
                "subId": sub_id,
                "reset": 0,
                "comment": (spec.note or "")[:200],
            }
            if tpl.get("flow"):
                client["flow"] = tpl["flow"]
            await self._req("POST", "/panel/api/clients/add", json={"client": client, "inboundIds": tpl["inboundIds"]})
        else:
            tpl = {"flow": self.cfg.get("flow", ""), "limitIp": _int(self.cfg.get("limit_ip"), 0)}
            c = self._legacy_client_obj(spec, tpl)
            await self._req("POST", "/panel/api/inbounds/addClient", json={"id": self.inbound_id, "settings": json.dumps({"clients": [c]})})
        created = await self.get_account(spec.username)
        if not created:
            raise PanelError(ErrorKind.UNKNOWN, "sanaei: client created but not readable yet")
        return created

    async def get_account(self, username: str) -> PanelAccount | None:
        if await self._api_style() == "v3":
            found = await self._v3_get(username)
            if not found:
                return None
            rec, ids = found
            traffic = await self._v3_traffic(username, rec)
            ref = f"{','.join(map(str, ids)) or '-'}:{rec.get('uuid') or rec.get('subId') or username}"
            return self._to_account(rec, traffic, ref, await self._links(username))
        found = await self._legacy_find(username)
        if not found:
            return None
        iid, c, st = found
        return self._to_account(c, st, f"{iid}:{self._legacy_cid(c)}")

    async def suspend_account(self, username: str) -> None:
        if await self._api_style() == "v3":
            await self._v3_update(username, enable=False)
        else:
            await self._legacy_update(username, enable=False)

    async def resume_account(self, username: str) -> None:
        if await self._api_style() == "v3":
            await self._v3_update(username, enable=True)
        else:
            await self._legacy_update(username, enable=True)

    async def extend_account(self, username: str, *, expire_at: dt.datetime | None, traffic_bytes: int) -> PanelAccount:
        changes = {"enable": True, "totalGB": int(traffic_bytes or 0), "expiryTime": to_ms(expire_at)}
        if await self._api_style() == "v3":
            await self._v3_update(username, **changes)
        else:
            await self._legacy_update(username, **changes)
        acc = await self.get_account(username)
        if not acc:
            raise PanelError(ErrorKind.UNKNOWN, "sanaei: client vanished after extend")
        return acc

    async def reset_traffic(self, username: str) -> PanelAccount:
        if await self._api_style() == "v3":
            await self._req("POST", f"/panel/api/clients/resetTraffic/{self._q(username)}")
        else:
            found = await self._legacy_find(username)
            if not found:
                raise PanelError(ErrorKind.PERMANENT, "sanaei: client not found on panel")
            await self._req("POST", f"/panel/api/inbounds/{found[0]}/resetClientTraffic/{self._q(username)}")
        acc = await self.get_account(username)
        if not acc:
            raise PanelError(ErrorKind.UNKNOWN, "sanaei: client vanished after traffic reset")
        return acc

    async def revoke_account(self, username: str) -> None:
        if await self._api_style() == "v3":
            await self._req("POST", f"/panel/api/clients/del/{self._q(username)}", ok_missing=True)
            return
        found = await self._legacy_find(username)
        if found:
            await self._req("POST", f"/panel/api/inbounds/{found[0]}/delClient/{self._q(self._legacy_cid(found[1]))}")

    def normalize_status(self, raw: str) -> str:
        raw = (raw or "").lower()
        return raw if raw in ("active", "disabled", "expired", "limited") else ("disabled" if raw == "depleted" else "unknown")

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            self._logged_in = False
