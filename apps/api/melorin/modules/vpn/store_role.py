"""PG-12 / L6: the role a store's panel admin should hold (``melorin-store``): plan, and an explicit admin ACTION to apply it.

Today store admins are created with the panel's stock ``operator`` role, which on the live panel carries ``api_keys`` (read/update/
delete, own scope): a reseller's admin could change or delete its own keys, which has no use for Melorin. This module states the
smallest permission set a store admin needs so an operator can create that role on the panel and compare it with ``operator``.

Nothing here runs by itself (decision 3: Melorin does not write panel settings on its own). :func:`apply` is a typed-name-confirmed
admin action: it creates (or brings to exactly this body) the ``melorin-store`` role with an owner credential used for that one
request, then records ``panel.config["admin_role"]`` so every store admin created or re-synced afterwards gets it. Existing admins
are not touched until their next sync (``panel_admins._push`` passes the role on every ensure). Rollback = ``revert``.
"""

from __future__ import annotations

import logging

from melorin.core import audit
from melorin.core.errors import AppError
from melorin.kernel.models.vpn import Panel
from melorin.modules.vpn.adapters import registry
from melorin.modules.vpn.adapters.base import PanelError

log = logging.getLogger("melorin.vpn.store_role")

STORE_ROLE_NAME = "melorin-store"
# Create / read / change / remove the store's own customers, and read the groups it may place them in. Nothing else.
STORE_PERMISSIONS = ("users.create", "users.read", "users.update", "users.delete", "groups.read")
WITHHELD = ("api_keys.*", "admins.*", "nodes.*", "hosts.*", "groups.create/update/delete", "cores.*", "settings.*")


def role_body() -> dict:
    perms: dict[str, dict[str, bool]] = {}
    for path in STORE_PERMISSIONS:
        section, _, action = path.partition(".")
        perms.setdefault(section, {})[action] = True
    return {"name": STORE_ROLE_NAME, "permissions": perms, "features": {}}


def applied_role(panel: Panel | None) -> str | None:
    role = ((panel.config or {}).get("admin_role") if panel is not None else None) or None
    return role if role == STORE_ROLE_NAME else None


def plan(current_role: str = "operator", panel: Panel | None = None) -> dict:
    return {
        "applied": applied_role(panel) is not None,
        "role": STORE_ROLE_NAME,
        "replaces": current_role,
        "grants": list(STORE_PERMISSIONS),
        "withheld": list(WITHHELD),
        "applied_by_melorin": False,
        "how": "Create the role on the panel with `body`, assign one test store admin, check a create/renew/delete round trip, then roll out.",
        "body": role_body(),
    }


def _creds(bootstrap: dict | None) -> dict | None:
    if not bootstrap:
        return None
    if bootstrap.get("api_key"):
        return {"api_key": str(bootstrap["api_key"])}
    if bootstrap.get("username") and bootstrap.get("password"):
        return {"username": str(bootstrap["username"]), "password": str(bootstrap["password"])}
    raise AppError("BOOTSTRAP_CREDENTIAL_INVALID", "Give an owner api_key, or username and password.", 422)


async def apply(session, panel: Panel, *, bootstrap: dict | None, actor_id=None) -> dict:
    """Create the role on the panel, then make it the role of new / re-synced store admins. Idempotent."""
    if panel.kind != "pasarguard":
        raise AppError("NOT_PASARGUARD", "The store role is only available for PasarGuard panels.", 422)
    creds = _creds(bootstrap)
    if creds is None:
        raise AppError("BOOTSTRAP_REQUIRED", "Creating a role needs an owner credential (used once, not stored).", 422)
    adapter = registry.build_adapter(panel, credentials=creds)
    try:
        try:
            role = await adapter.ensure_role(role_body())
        except PanelError as exc:
            detail = (getattr(exc, "message", None) or str(exc))[:200]
            raise AppError("STORE_ROLE_FAILED", f"Panel refused the role: {detail}", 502) from exc
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            try:
                res = close()
                if hasattr(res, "__await__"):
                    await res
            except Exception:
                log.debug("store role: adapter close failed", exc_info=True)
    previous = (panel.config or {}).get("admin_role")
    panel.config = {**(panel.config or {}), "admin_role": STORE_ROLE_NAME}
    audit.record(
        session,
        "panel.store_role.applied",
        actor_id=actor_id,
        actor_type="admin",
        entity_type="panel",
        entity_id=panel.id,
        data={"role": STORE_ROLE_NAME, "role_id": role.get("id") if isinstance(role, dict) else None, "previous": previous},
    )
    await session.commit()
    return {
        "applied": True,
        "role": STORE_ROLE_NAME,
        "previous": previous or "operator",
        "note": "New and re-synced store admins get this role; existing admins change on their next sync.",
    }


async def revert(session, panel: Panel, *, actor_id=None) -> dict:
    """Stop using the role for new / re-synced admins (back to the panel's stock role). Writes nothing to the panel."""
    cfg = dict(panel.config or {})
    had = cfg.pop("admin_role", None)
    panel.config = cfg
    audit.record(
        session,
        "panel.store_role.reverted",
        actor_id=actor_id,
        actor_type="admin",
        entity_type="panel",
        entity_id=panel.id,
        data={"was": had},
    )
    await session.commit()
    return {"applied": False, "role": "operator"}
