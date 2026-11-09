"""PasarGuard admins: one Operator admin per store, profile fields, bulk owner moves."""

from melorin.modules.vpn.adapters.base import ErrorKind, PanelError


class AdminsMixin:
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
        """Create the admin when missing, adopt it (set our password, move it to ``role`` unless it is an owner) when it exists. Idempotent."""
        existing = await self.find_admin(username)
        if existing:
            body: dict = {"password": password, **self._profile_body(profile)}
            current = existing.get("role") if isinstance(existing.get("role"), dict) else {}
            if not current.get("is_owner"):  # an owner's role is never touched, whatever the caller asks for
                wanted = await self._role_id(role)
                have = current.get("id") if current.get("id") is not None else existing.get("role_id")
                if have is None or int(have) != wanted:
                    body["role_id"] = wanted  # PG-12: applying `melorin-store` must reach admins that already exist
            await self._req("PUT", f"/api/admin/by-id/{int(existing['id'])}", json=body)
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

    @staticmethod
    def parse_custom_variables(raw) -> dict:
        """The admin's ``custom_variables`` as a flat ``{KEY: value}`` dict with UPPER-CASE keys.

        PasarGuard 5.6.0 keeps a LIST of ``{"key", "value"}`` (``CustomVariable``) and upper-cases every key (read from the panel's own
        models, 9 Nov 2026). An object or a JSON string is still tolerated so an older/other build cannot break a read.
        """
        import json

        if isinstance(raw, str):
            try:
                raw = json.loads(raw) if raw.strip() else []
            except ValueError:
                return {}
        out: dict[str, str] = {}
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict) and item.get("key") and isinstance(item.get("value", ""), str | int | float):
                    out[str(item["key"]).strip().upper()] = str(item.get("value", ""))
            return out
        if isinstance(raw, dict):
            return {str(k).strip().upper(): str(v) for k, v in raw.items() if isinstance(v, str | int | float)}
        return {}

    async def read_custom_variables(self, username: str) -> dict | None:
        """What the panel holds in the admin's ``custom_variables`` now (``None`` when the admin does not exist). Read-only."""
        admin = await self.find_admin(username)
        return None if admin is None else self.parse_custom_variables(admin.get("custom_variables"))

    async def write_custom_variables(self, remote_id: int, variables: dict[str, str]) -> dict:
        """Replace the admin's ``custom_variables`` with exactly ``variables`` (callers merge first). Touches nothing else.

        Wire format: a list of ``{"key", "value"}``. An object is refused by the panel with 422 ``list_type`` (checked against 5.6.0).
        """
        body = [{"key": str(k).strip().upper(), "value": str(v)} for k, v in sorted(variables.items())]
        return await self._req("PUT", f"/api/admin/by-id/{int(remote_id)}", json={"custom_variables": body})

    async def bulk_set_owner(self, refs: list[str], owner: str) -> int:
        """Move existing users (panel ids) under ``owner``; chunked, idempotent."""
        ids = [int(r) for r in refs if str(r).isdigit()]
        for i in range(0, len(ids), 200):
            await self._req("PUT", "/api/users/bulk/set_owner", json={"ids": ids[i : i + 200], "admin_username": owner})
        return len(ids)
