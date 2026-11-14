"""PasarGuard infrastructure listings: groups, user templates, destination picker (and, below, nodes)."""

from melorin.modules.panel_integrations.adapters.base import ErrorKind, PanelError
from melorin.modules.panel_integrations.adapters.pasarguard.core import as_rows

NODE_PAGE = 100
NODE_MAX_PAGES = 50  # 5,000 nodes: far beyond any real panel, but a runaway loop is never acceptable


class NodesMixin:
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

    # ------------------------------------------------------------------ capacity listings (CapacityOps, PG-08)
    async def _paged(self, path: str, *keys: str) -> list[dict]:
        rows: list[dict] = []
        for page in range(NODE_MAX_PAGES):
            data = await self._req("GET", path, params={"limit": NODE_PAGE, "offset": page * NODE_PAGE})
            batch = as_rows(data, *keys)
            rows.extend(batch)
            total = data.get("total") if isinstance(data, dict) else None
            if len(batch) < NODE_PAGE or (isinstance(total, int) and len(rows) >= total):
                break
        return rows

    async def list_groups_full(self) -> list[dict]:
        """Every group with ``total_users``, ``is_disabled`` and its ``inbound_tags`` (what ``/groups/simple`` leaves out)."""
        return [g for g in await self._paged("/api/groups", "groups", "items") if g.get("id") is not None]

    async def list_hosts(self) -> list[dict]:
        """Every host (``inbound_tag``, ``is_disabled``, ...): a group serves customers only through an enabled host."""
        return await self._paged("/api/hosts", "hosts", "items")

    async def list_inbound_details(self) -> list[dict]:
        data = await self._req("GET", "/api/inbounds/details", ok404=True)
        return as_rows(data, "inbounds", "items")

    # ------------------------------------------------------------------ templates (TemplateOps, PG-09)
    @staticmethod
    def _template_body(spec: dict) -> dict:
        """Only the fields a package defines; absolute values so a repeated call changes nothing."""
        body: dict = {}
        for key in ("name", "username_prefix", "username_suffix", "status", "data_limit_reset_strategy"):
            if spec.get(key) is not None:
                body[key] = spec[key]
        for key in ("data_limit", "expire_duration", "hwid_limit", "on_hold_timeout"):
            if spec.get(key) is not None:
                body[key] = int(spec[key])
        if spec.get("group_ids") is not None:
            body["group_ids"] = [int(g) for g in spec["group_ids"]]
        if spec.get("reset_usages") is not None:
            body["reset_usages"] = bool(spec["reset_usages"])
        return body

    async def create_template(self, spec: dict) -> dict:
        body = self._template_body(spec)
        if not body.get("name") or not body.get("group_ids"):
            raise PanelError(ErrorKind.PERMANENT, "pasarguard: a template needs a name and at least one group")
        out = await self._req("POST", "/api/user_template", json=body)
        return out if isinstance(out, dict) else {}

    async def update_template(self, template_id: int, spec: dict) -> dict:
        out = await self._req("PUT", f"/api/user_template/{int(template_id)}", json=self._template_body(spec))
        return out if isinstance(out, dict) else {}

    async def set_template_disabled(self, template_id: int, disabled: bool) -> dict:
        action = "disable" if disabled else "enable"
        out = await self._req("POST", f"/api/user_templates/bulk/{action}", json={"ids": [int(template_id)]})
        return out if isinstance(out, dict) else {}

    # ------------------------------------------------------------------ nodes (NodeOps)
    async def list_nodes(self) -> list[dict]:
        """Every node with its status (``connected|connecting|error|disabled|limited``) and error ``message``. Read-only, paged."""
        rows: list[dict] = []
        for page in range(NODE_MAX_PAGES):
            data = await self._req("GET", "/api/nodes", params={"limit": NODE_PAGE, "offset": page * NODE_PAGE})
            batch = as_rows(data, "nodes", "items")
            rows.extend(batch)
            total = data.get("total") if isinstance(data, dict) else None
            if len(batch) < NODE_PAGE or (isinstance(total, int) and len(rows) >= total):
                break
        return rows

    async def get_node(self, node_id: int) -> dict | None:
        data = await self._req("GET", f"/api/node/{int(node_id)}", ok404=True)
        return data if isinstance(data, dict) and data else None

    async def reconnect_node(self, node_id: int) -> None:
        """Ask the panel to re-establish its connection to one node (safe to repeat)."""
        await self._req("POST", f"/api/node/{int(node_id)}/reconnect")

    # ------------------------------------------------------------------ settings (SettingsOps, read-only)
    async def get_settings(self) -> dict:
        data = await self._req("GET", "/api/settings")
        return data if isinstance(data, dict) else {}
