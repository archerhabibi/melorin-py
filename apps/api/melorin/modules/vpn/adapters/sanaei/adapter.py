"""Sanaei adapter: transport (login/request), API-style detection and the PanelAdapter port."""

import datetime as dt
import json
import secrets
from urllib.parse import quote, urlsplit

import httpx

from melorin.modules.vpn.adapters.base import AccountSpec, Capabilities, ErrorKind, PanelAccount, PanelError
from melorin.modules.vpn.adapters.sanaei.wire import as_int, classify, from_ms, is_not_found, to_ms
from melorin.modules.vpn.adapters.sanaei.legacy import LegacyMixin
from melorin.modules.vpn.adapters.sanaei.v3 import V3Mixin


class SanaeiAdapter(V3Mixin, LegacyMixin):
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
            raise PanelError(classify(r.status_code), f"sanaei: login http {r.status_code}")
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
            raise PanelError(classify(r.status_code), f"sanaei: http {r.status_code} on {path}")
        try:
            data = r.json()
        except ValueError as e:
            raise PanelError(ErrorKind.PERMANENT, f"sanaei: non-JSON response on {path} (wrong base_url?)") from e
        if not isinstance(data, dict):
            raise PanelError(ErrorKind.PERMANENT, f"sanaei: unexpected response on {path}")
        if data.get("success") is False:
            if ok_missing and is_not_found(data):
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
            raise PanelError(classify(r.status_code), f"sanaei: api probe http {r.status_code}")
        return self._style

    def _to_account(self, c: dict, traffic: dict, ref: str, links: list[str] | None = None) -> PanelAccount:
        expire_at = from_ms(c.get("expiryTime", traffic.get("expiryTime")))
        total = as_int(c.get("totalGB", traffic.get("total")), 0)
        used = max(0, as_int(traffic.get("up")) + as_int(traffic.get("down")))
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
                "limitIp": as_int(spec.max_devices or tpl.get("limitIp"), 0),
                "tgId": 0,
                "subId": sub_id,
                "reset": 0,
                "comment": (spec.note or "")[:200],
            }
            if tpl.get("flow"):
                client["flow"] = tpl["flow"]
            await self._req("POST", "/panel/api/clients/add", json={"client": client, "inboundIds": tpl["inboundIds"]})
        else:
            tpl = {"flow": self.cfg.get("flow", ""), "limitIp": as_int(self.cfg.get("limit_ip"), 0)}
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
