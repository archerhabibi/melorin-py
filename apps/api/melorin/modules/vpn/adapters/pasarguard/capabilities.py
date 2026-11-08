"""PasarGuard capability model (PG-00): what this adapter implements, and what the connected credential may actually do.

Two layers:

* **declared** - the adapter implements the methods (``PasarGuardAdapter.declared_capabilities``). Static.
* **permitted** - the panel's own role/permissions for the credential Melorin logged in with (``GET /api/admin``). Probed when a
  panel is registered or edited (see ``modules/vpn/capabilities.py``) and stored in ``panels.capabilities``.

The effective capability is declared AND permitted. ``CAPABILITY_REQUIREMENTS`` is the single table that ties a capability to the
panel permissions it needs; ``CAPABILITY_ENDPOINTS`` lists the routes behind it. Both are checked against the committed PasarGuard
OpenAPI contract fixture (``tests/test_pasarguard_openapi_contract.py``), so a panel upgrade that renames a permission or removes
a route is caught in CI, not by a customer.
"""

from melorin.modules.vpn.adapters.base import ALL_CAPABILITIES, Capabilities, CapabilityReport, PanelError

# capability -> permissions (``section.action``) the credential needs, ALL of them
CAPABILITY_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "suspend": ("users.update",),
    "extend": ("users.update",),
    "subscription_url": ("users.read",),
    "traffic_reset": ("users.reset_usage",),
    "subscription_rotate": ("users.revoke_sub",),
    "node_ops": ("nodes.read",),
    "node_control": ("nodes.read", "nodes.reconnect"),
    "usage_ops": ("users.read",),
    "device_ops": ("hwids.read", "hwids.delete"),
    "bulk_ops": ("users.set_owner",),
    "admin_ops": ("admins.read", "admins.create", "admins.update"),
    "settings_ops": ("settings.read",),
    "account_listing": ("users.read",),
    "capacity_ops": ("groups.read", "hosts.read", "nodes.read"),
    "template_ops": ("templates.read", "templates.create", "templates.update"),
    "next_plan_ops": ("users.update", "users.activate_next_plan"),
    "event_source": ("settings.read", "settings.update"),
    # Phase 4
    "node_insight": ("system.read", "nodes.stats"),
    "infra_control": ("nodes.update", "hosts.update", "groups.update", "cores.read", "cores.update"),
    "bulk_actions": ("users.update", "users.reset_usage", "users.revoke_sub", "admins.update"),
    "admin_governance": ("admins.read", "admins.update"),
    "subscription_probe": ("settings.read",),
    # decision 5: IPs are an admin-only view. ``nodes.stats`` reads the live IPs, ``users.read`` the subscription-fetch history
    "ip_ops": ("nodes.stats", "users.read"),
}

# capability -> "METHOD /path-template" routes the adapter calls for it (current, non-legacy API style)
CAPABILITY_ENDPOINTS: dict[str, tuple[str, ...]] = {
    "suspend": ("PUT /api/user/by-id/{user_id}",),
    "extend": ("PUT /api/user/by-id/{user_id}",),
    "subscription_url": ("GET /api/user/by-username/{username}",),
    "traffic_reset": ("POST /api/user/by-id/{user_id}/reset",),
    "subscription_rotate": ("POST /api/user/by-id/{user_id}/revoke_sub",),
    "node_ops": ("GET /api/nodes", "GET /api/node/{node_id}"),
    "node_control": ("POST /api/node/{node_id}/reconnect",),
    "usage_ops": ("GET /api/user/by-id/{user_id}/usage",),
    "device_ops": ("GET /api/user/{user_id}/hwids", "DELETE /api/user/{user_id}/hwids/{hwid}", "POST /api/user/{user_id}/hwids/reset"),
    "bulk_ops": ("PUT /api/users/bulk/set_owner",),
    "admin_ops": ("GET /api/admins", "POST /api/admin", "PUT /api/admin/by-id/{admin_id}", "GET /api/admin-roles/simple"),
    "settings_ops": ("GET /api/settings",),
    "account_listing": ("GET /api/users",),
    "capacity_ops": ("GET /api/groups", "GET /api/hosts", "GET /api/inbounds/details"),
    "template_ops": (
        "GET /api/user_templates",
        "POST /api/user_template",
        "PUT /api/user_template/{template_id}",
        "POST /api/user_templates/bulk/enable",
        "POST /api/user_templates/bulk/disable",
    ),
    "next_plan_ops": (
        "PUT /api/user/by-id/{user_id}",
        "POST /api/user/by-id/{user_id}/active_next",
        "PUT /api/user/from_template/by-id/{user_id}",
    ),
    # Phase 2: the panel calls Melorin (``/webhooks/pasarguard/{panel_id}``); the only panel routes involved switch the webhook on/off
    "event_source": ("GET /api/settings", "PUT /api/settings"),
    # Phase 4
    "node_insight": ("GET /api/system", "GET /api/system/resources", "GET /api/nodes/realtime_stats", "GET /api/node/{node_id}/stats"),
    "infra_control": (
        "PUT /api/node/{node_id}/sync",
        "GET /api/cores",
        "POST /api/core/{core_id}/restart",
        "POST /api/nodes/bulk/enable",
        "POST /api/nodes/bulk/disable",
        "POST /api/hosts/bulk/enable",
        "POST /api/hosts/bulk/disable",
        "POST /api/groups/bulk/enable",
        "POST /api/groups/bulk/disable",
    ),
    "bulk_actions": (
        "POST /api/users/bulk/disable",
        "POST /api/users/bulk/enable",
        "POST /api/users/bulk/reset",
        "POST /api/users/bulk/revoke_sub",
        "POST /api/admin/by-id/{admin_id}/users/disable",
        "POST /api/admin/by-id/{admin_id}/users/activate",
    ),
    "admin_governance": ("GET /api/admins", "PUT /api/admin/by-id/{admin_id}"),
    # the public ``/sub/{token}/info`` fetch is made without credentials by the probe itself, so it is not a panel API call listed here
    "subscription_probe": ("GET /api/settings",),
    "ip_ops": ("GET /api/node/online_stats/{user_id}/ip", "GET /api/user/by-id/{user_id}/sub_update"),
}

# Capabilities of the legacy (Marzban-style) API: only what the pre-capability adapter did.
LEGACY_CAPABILITIES = frozenset({"suspend", "extend", "subscription_url", "traffic_reset", "subscription_rotate"})
# Declared but switched off until their phase ships (empty since Phase 2 shipped ``event_source``).
NOT_YET: frozenset[str] = frozenset()

PERMISSION_FALSE_VALUES = (None, False, 0, "0", "", "none", "None")


def permission_granted(permissions: dict | None, path: str) -> bool:
    """``users.read`` -> truthy flag in ``permissions["users"]["read"]``. PasarGuard mixes booleans with scopes
    (0 none / 1 own / 2 all), so anything that is not an explicit 'no' counts as granted."""
    section, _, action = path.partition(".")
    block = (permissions or {}).get(section)
    if not isinstance(block, dict):
        return False
    value = block.get(action)
    return value not in PERMISSION_FALSE_VALUES


def merge_permissions(base: dict | None, overrides: dict | None) -> dict:
    """Role permissions with the admin's own ``permission_overrides`` on top (section by section, action by action)."""
    merged = {k: dict(v) if isinstance(v, dict) else v for k, v in (base or {}).items()}
    for section, block in (overrides or {}).items():
        if isinstance(block, dict):
            target = merged.get(section)
            merged[section] = {**(target if isinstance(target, dict) else {}), **{k: v for k, v in block.items() if v is not None}}
    return merged


def missing_permissions(permissions: dict | None, capability: str) -> list[str]:
    return [p for p in CAPABILITY_REQUIREMENTS.get(capability, ()) if not permission_granted(permissions, p)]


def users_scope(permissions: dict | None) -> int | None:
    value = ((permissions or {}).get("users") or {}).get("read") if isinstance((permissions or {}).get("users"), dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def build_report(declared: Capabilities, *, role: str | None, is_owner: bool, permissions: dict | None) -> CapabilityReport:
    """Pure function: declared capabilities + the credential's permissions -> effective capabilities and the reasons for denials."""
    flags: dict[str, bool] = {}
    denied: dict[str, list[str]] = {}
    for name in ALL_CAPABILITIES:
        if not declared.has(name):
            flags[name] = False
            continue
        missing = [] if is_owner else missing_permissions(permissions, name)
        flags[name] = not missing
        if missing:
            denied[name] = missing
    return CapabilityReport(
        capabilities=Capabilities(**flags),
        declared=declared,
        denied=denied,
        role=role,
        is_owner=is_owner,
        users_scope=users_scope(permissions),
        source="probe",
    )


class CapabilitiesMixin:
    """``declared_capabilities`` / ``capabilities`` / ``discover_capabilities`` for the PasarGuard adapter."""

    def declared_capabilities(self) -> Capabilities:
        names = LEGACY_CAPABILITIES if self.legacy else frozenset(ALL_CAPABILITIES) - NOT_YET
        return Capabilities(**{name: name in names for name in ALL_CAPABILITIES})

    def capabilities(self) -> Capabilities:
        return self.declared_capabilities()

    async def _role_permissions(self, role: str | dict | None) -> tuple[str | None, bool, dict | None]:
        """(role name, is_owner, permissions) from the ``role`` field of ``GET /api/admin``; looks the role up by name when the
        panel only returned a name."""
        if isinstance(role, dict):
            name = str(role.get("name") or "") or None
            perms = role.get("permissions") if isinstance(role.get("permissions"), dict) else None
            if perms is None and name and not role.get("is_owner"):
                perms = await self._lookup_role_permissions(name)
            return name, bool(role.get("is_owner")), perms
        if isinstance(role, str) and role.strip():
            return role.strip(), False, await self._lookup_role_permissions(role.strip())
        return None, False, None

    async def _lookup_role_permissions(self, name: str) -> dict | None:
        try:
            data = await self._req("GET", "/api/admin-roles", params={"search": name, "limit": 50}, ok404=True)
        except PanelError:
            return None  # the credential may not read roles; the caller falls back to the static declaration
        rows = data.get("roles") if isinstance(data, dict) else data
        for row in rows or []:
            if (
                isinstance(row, dict)
                and str(row.get("name", "")).strip().lower() == name.lower()
                and isinstance(row.get("permissions"), dict)
            ):
                return row["permissions"]
        return None

    async def discover_capabilities(self) -> CapabilityReport:
        """Read the connected admin's role and permissions and compute the effective capabilities. Never raises: an unreachable
        panel or a role whose permissions are not exposed degrades to the static declaration with ``error`` set."""
        declared = self.declared_capabilities()
        try:
            admin = await self._req("GET", "/api/admin")
        except PanelError as exc:
            return CapabilityReport(capabilities=declared, declared=declared, source="static", error=exc.message[:300])
        if not isinstance(admin, dict):
            return CapabilityReport(capabilities=declared, declared=declared, source="static", error="unexpected /api/admin response")
        role, is_owner, perms = await self._role_permissions(admin.get("role"))
        if not is_owner and perms is None:
            return CapabilityReport(
                capabilities=declared,
                declared=declared,
                role=role,
                source="static",
                error="role permissions are not exposed to this credential",
            )
        perms = merge_permissions(perms, admin.get("permission_overrides") if isinstance(admin.get("permission_overrides"), dict) else None)
        return build_report(declared, role=role, is_owner=is_owner, permissions=perms)
