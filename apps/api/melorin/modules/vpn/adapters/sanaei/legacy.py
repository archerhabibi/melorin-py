"""3x-ui 1.x/2.x (clients live inside inbound.settings.clients)."""

import json
import secrets
import uuid


from melorin.modules.vpn.adapters.base import AccountSpec, ErrorKind, PanelError
from melorin.modules.vpn.adapters.sanaei.wire import as_int, parse_settings, to_ms


class LegacyMixin:
    def _legacy_client_obj(self, spec: AccountSpec, tpl: dict) -> dict:
        return {
            "id": str(uuid.uuid4()),
            "password": secrets.token_urlsafe(12),
            "email": spec.username,
            "enable": True,
            "flow": tpl.get("flow", ""),
            "limitIp": as_int(spec.max_devices or tpl.get("limitIp"), 0),
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
            for c in parse_settings(inbound).get("clients", []) or []:
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
        c["tgId"] = as_int(c.get("tgId"), 0)
        await self._req(
            "POST",
            f"/panel/api/inbounds/updateClient/{self._q(self._legacy_cid(c))}",
            json={"id": iid, "settings": json.dumps({"clients": [c]})},
        )
