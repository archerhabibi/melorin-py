"""PasarGuard access management (PG-05): the least-privilege role, the service admin's API key, and listing / deleting keys.

Only an owner-level credential may call these (they create roles and keys). They are used by ``modules/vpn_accounts/service_access.py`` with a
credential the operator supplies for that one request; the credential Melorin runs on cannot do any of this by design.
Request shapes are taken from the live panel's OpenAPI 5.6.0 (``AdminRoleCreate``, ``APIKeyCreate``)."""

from melorin.modules.panel_integrations.adapters.base import ErrorKind, PanelError


class AccessMixin:
    async def find_role(self, name: str) -> dict | None:
        data = await self._req("GET", "/api/admin-roles", params={"search": name, "limit": 50})
        rows = data.get("roles") if isinstance(data, dict) else data
        for row in rows or []:
            if isinstance(row, dict) and str(row.get("name", "")).strip().lower() == name.strip().lower():
                return row
        return None

    async def ensure_role(self, body: dict) -> dict:
        """Create the role, or bring an existing one of that name to exactly ``body``. Idempotent."""
        existing = await self.find_role(str(body["name"]))
        if existing:
            if existing.get("is_owner"):
                raise PanelError(ErrorKind.PERMANENT, "pasarguard: refusing to modify an owner role")
            out = await self._req("PUT", f"/api/admin-role/{int(existing['id'])}", json=body)
            return out if isinstance(out, dict) and out.get("id") else existing
        return await self._req("POST", "/api/admin-role", json=body)

    async def list_api_keys(self, admin_id: int | None = None) -> list[dict]:
        """Keys (never their secret values). ``admin_id`` filters on our side: the panel's list has no owner filter."""
        data = await self._req("GET", "/api/api_keys", params={"limit": 200})
        rows = data.get("api_keys") if isinstance(data, dict) else data
        out = [r for r in rows or [] if isinstance(r, dict)]
        return [r for r in out if admin_id is None or int(r.get("admin_id") or 0) == int(admin_id)]

    async def create_api_key(self, admin_id: int, name: str, note: str | None = None) -> dict:
        """A key owned by ``admin_id`` that inherits that admin's role. The response carries the secret ONCE (``api_key``)."""
        body = {"name": name[:128], "note": (note or "")[:512] or None, "inherit_permissions": True, "admin_id": int(admin_id)}
        return await self._req("POST", "/api/api_key", json=body)

    async def delete_api_key(self, key_id: int) -> None:
        await self._req("DELETE", f"/api/api_key/{int(key_id)}", ok404=True)
