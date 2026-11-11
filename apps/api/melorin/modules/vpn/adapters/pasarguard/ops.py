"""PasarGuard Phase 4 operations: console insight + infra control (PG-07), bulk actions (PG-11), store-admin governance (PG-12),
subscription probe (PG-13).

Design rules (doc: PasarGuard roadmap section 3):
* every write is ABSOLUTE and idempotent: "set disabled=true", "disable these users" - repeating a call changes nothing, so a
  timeout can always be retried (``ErrorKind.UNKNOWN`` -> safe to run again);
* relative panel endpoints (``/users/bulk/expire``, ``/users/bulk/data_limit`` add/subtract an amount) are deliberately NOT used:
  a repeat would apply twice. Time/traffic compensation goes through ``extend_account`` with an absolute value instead;
* ids are sent in chunks of ``BULK_CHUNK`` (the panel's own bulk limit used by ``bulk_set_owner``)."""

from urllib.parse import urlsplit

import httpx

from melorin.modules.vpn.adapters.base import ErrorKind, PanelError
from melorin.modules.vpn.adapters.pasarguard.core import as_rows
from melorin.core.http import outbound_client

BULK_CHUNK = 200
USER_ACTIONS = {"disable": "disable", "enable": "enable", "reset_usage": "reset", "rotate_links": "revoke_sub"}


def _ids(values) -> list[int]:
    return sorted({int(v) for v in values if str(v).lstrip("-").isdigit() and int(v) > 0})


class OpsMixin:
    # ------------------------------------------------------------------ NodeInsight (read-only)
    async def get_system_stats(self) -> dict:
        data = await self._req("GET", "/api/system")
        return data if isinstance(data, dict) else {}

    async def get_system_resources(self) -> dict:
        data = await self._req("GET", "/api/system/resources", ok404=True)
        return data if isinstance(data, dict) else {}

    async def get_nodes_realtime(self) -> dict[int, dict | None]:
        data = await self._req("GET", "/api/nodes/realtime_stats", ok404=True)
        out: dict[int, dict | None] = {}
        for key, value in (data or {}).items() if isinstance(data, dict) else []:
            if str(key).isdigit():
                out[int(key)] = value if isinstance(value, dict) else None
        return out

    async def get_node_stats(self, node_id: int) -> dict:
        data = await self._req("GET", f"/api/node/{int(node_id)}/stats", params={"period": "hour"}, ok404=True)
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------ InfraControl
    async def sync_node(self, node_id: int) -> None:
        """Re-send the core configuration and users to one node (``flush_users`` stays off: no user is dropped)."""
        await self._req("PUT", f"/api/node/{int(node_id)}/sync", params={"flush_users": "false"})

    async def list_cores(self) -> list[dict]:
        data = await self._req("GET", "/api/cores", params={"limit": 100, "offset": 0})
        return as_rows(data, "cores", "items")

    async def restart_core(self, core_id: int) -> None:
        await self._req("POST", f"/api/core/{int(core_id)}/restart")

    async def _bulk_toggle(self, family: str, ids: list[int], disabled: bool) -> int:
        clean = _ids(ids)
        action = "disable" if disabled else "enable"
        for i in range(0, len(clean), BULK_CHUNK):
            await self._req("POST", f"/api/{family}/bulk/{action}", json={"ids": clean[i : i + BULK_CHUNK]})
        return len(clean)

    async def set_nodes_disabled(self, ids: list[int], disabled: bool) -> int:
        return await self._bulk_toggle("nodes", ids, disabled)

    async def set_hosts_disabled(self, ids: list[int], disabled: bool) -> int:
        return await self._bulk_toggle("hosts", ids, disabled)

    async def set_groups_disabled(self, ids: list[int], disabled: bool) -> int:
        return await self._bulk_toggle("groups", ids, disabled)

    # ------------------------------------------------------------------ BulkActions
    async def bulk_users_action(self, refs: list[str], action: str) -> int:
        """``disable | enable | reset_usage | rotate_links`` over panel user ids, chunked. Idempotent by construction."""
        if action not in USER_ACTIONS:
            raise PanelError(ErrorKind.PERMANENT, f"pasarguard: unsupported bulk action '{action}'")
        ids = _ids(refs)
        for i in range(0, len(ids), BULK_CHUNK):
            await self._req("POST", f"/api/users/bulk/{USER_ACTIONS[action]}", json={"ids": ids[i : i + BULK_CHUNK]})
        return len(ids)

    async def set_admin_users_state(self, remote_id: int, *, active: bool) -> None:
        """Disable every active user of one panel admin (a suspended store) or re-activate every disabled one."""
        await self._req("POST", f"/api/admin/by-id/{int(remote_id)}/users/{'activate' if active else 'disable'}")

    # ------------------------------------------------------------------ AdminGovernance
    async def get_admin_detail(self, remote_id: int) -> dict | None:
        """One admin with ``total_users`` / ``used_traffic`` / ``data_limit`` / ``status`` (looked up in the admin list by id)."""
        data = await self._req("GET", "/api/admins", params={"ids": [int(remote_id)], "limit": 1})
        for row in as_rows(data, "admins", "items"):
            if row.get("id") == int(remote_id):
                return row
        return None

    async def update_admin_limits(
        self, remote_id: int, *, data_limit: int | None = None, status: str | None = None, notifications_off: bool | None = None
    ) -> dict:
        """Absolute values only. ``data_limit`` bytes (0 = unlimited), ``status`` active|disabled, ``notifications_off`` stops the
        panel's own notifications to that admin so customers hear from Melorin only."""
        body: dict = {}
        if data_limit is not None:
            if int(data_limit) < 0:
                raise PanelError(ErrorKind.PERMANENT, "pasarguard: data_limit must be >= 0")
            body["data_limit"] = int(data_limit)
        if status is not None:
            if status not in ("active", "disabled"):
                raise PanelError(ErrorKind.PERMANENT, "pasarguard: admin status must be active or disabled")
            body["status"] = status
        if notifications_off is not None:
            on = not notifications_off
            keys = ("create", "modify", "delete", "status_change", "reset_data_usage", "data_reset_by_next", "subscription_revoked")
            body["notification_enable"] = dict.fromkeys(keys, on)
        if not body:
            return {}
        out = await self._req("PUT", f"/api/admin/by-id/{int(remote_id)}", json=body)
        return out if isinstance(out, dict) else {}

    # ------------------------------------------------------------------ SubscriptionProbe
    async def get_subscription_settings(self) -> dict:
        data = await self._req("GET", "/api/settings")
        sub = data.get("subscription") if isinstance(data, dict) else None
        return sub if isinstance(sub, dict) else {}

    async def probe_subscription(self, url: str, *, allowed_hosts: set[str]) -> dict:
        """GET ``<subscription_url>/info`` (public, no credentials) and report ``{ok, status, error}``.

        SSRF guard: the URL comes from a panel response, so it is fetched only when its host is one Melorin was told to trust
        (the panel's own host, ``sub_base_url`` or the panel's ``url_prefix``), over http(s), without following redirects."""
        parts = urlsplit(url or "")
        host = (parts.hostname or "").lower()
        if parts.scheme not in ("http", "https") or not host:
            return {"ok": False, "status": None, "error": "invalid subscription url"}
        if host not in {h.lower() for h in allowed_hosts if h}:
            return {"ok": False, "status": None, "error": "host is not a configured subscription host"}
        target = url.split("?", 1)[0].rstrip("/") + "/info"
        try:
            async with outbound_client(
                "panel_pasarguard_ops", timeout=self.timeout, follow_redirects=False, verify=self.cfg.get("verify_tls", True)
            ) as c:
                r = await c.get(target)
        except httpx.HTTPError as exc:
            return {"ok": False, "status": None, "error": f"{exc.__class__.__name__}: {str(exc)[:160]}"}
        ok = r.status_code == 200
        return {"ok": ok, "status": r.status_code, "error": None if ok else f"http {r.status_code}"}
