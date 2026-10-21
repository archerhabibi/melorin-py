"""3x-ui 3.x (clients are first-class rows under /panel/api/clients/*)."""

import time


from melorin.modules.vpn.adapters.base import ErrorKind, PanelError
from melorin.modules.vpn.adapters.sanaei.wire import TEMPLATE_TTL, as_int, clean_client


class V3Mixin:
    async def _links(self, email: str) -> list[str]:
        if not self.cfg.get("fetch_links", True):
            return []
        try:
            d = await self._req("GET", f"/panel/api/clients/links/{self._q(email)}", ok_missing=True)
        except PanelError:
            return []  # links are cosmetic; subscription URL is the deliverable
        obj = (d or {}).get("obj")
        return [x for x in obj if isinstance(x, str)] if isinstance(obj, list) else []

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
            return {"inboundIds": self.inbound_ids, "flow": self.cfg.get("flow", ""), "limitIp": as_int(self.cfg.get("limit_ip"), 0)}
        if self._template and self._template[1] > time.monotonic():
            return self._template[0]
        found = await self._v3_get(name)
        if not found:  # never cache a miss
            raise PanelError(ErrorKind.PERMANENT, f"sanaei: template client '{name}' not found on panel")
        rec, ids = found
        tpl = {
            "inboundIds": self.inbound_ids or ids,
            "flow": self.cfg.get("flow", rec.get("flow") or ""),
            "limitIp": as_int(self.cfg.get("limit_ip", rec.get("limitIp")), 0),
        }
        self._template = (tpl, time.monotonic() + TEMPLATE_TTL)
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
