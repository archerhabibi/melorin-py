"""PG-12 / L6: the role a store's panel admin should hold (``melorin-store``): plan, and an explicit admin ACTION to apply it.

Today store admins are created with the panel's stock ``operator`` role, which on the live panel carries ``api_keys`` (read/update/
delete, own scope): a reseller's admin could change or delete its own keys, which has no use for Melorin. This module states the
smallest permission set a store admin needs so an operator can create that role on the panel and compare it with ``operator``.

Nothing here runs by itself (decision 3: Melorin does not write panel settings on its own). :func:`apply` is a typed-name-confirmed
admin action: it creates (or brings to exactly this body) the store role (default name ``melorin-store``; the admin may pick another name per panel) with an owner credential used for that one
request, then records ``panel.config["admin_role"]`` so every store admin created or re-synced afterwards gets it. Existing admins
are not touched until their next sync (``panel_admins._push`` passes the role on every ensure). Rollback = ``revert``.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import update

from melorin.core import audit
from melorin.core.errors import AppError
from melorin.core.uow import unit_of_work
from melorin.kernel.models.vpn import Panel, PanelAdmin
from melorin.modules.panel_integrations.adapters import registry
from melorin.modules.panel_integrations.adapters.base import PanelError
from melorin.modules.panel_integrations.adapters.lifecycle import close_adapter

log = logging.getLogger("melorin.vpn.store_role")

STORE_ROLE_NAME = "melorin-store"  # the DEFAULT name; the admin may choose another per panel (see normalize_role_name)
# Names the panel (or Melorin's service access) already uses: a store role must never take one of them over.
RESERVED_ROLE_NAMES = frozenset({"owner", "administrator", "operator", "melorin-service"})
_ROLE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")
# Create / read / change / remove the store's own customers, and read the groups it may place them in. Nothing else.
STORE_PERMISSIONS = ("users.create", "users.read", "users.update", "users.delete", "groups.read")
WITHHELD = ("api_keys.*", "admins.*", "nodes.*", "hosts.*", "groups.create/update/delete", "cores.*", "settings.*")


def normalize_role_name(name: str | None) -> str:
    """The role name an admin chose (default ``melorin-store``). 2-32 chars of a-z 0-9 ``-`` ``_``; reserved names are refused."""
    value = (name or "").strip() or STORE_ROLE_NAME
    if not _ROLE_NAME_RE.match(value):
        raise AppError("ROLE_NAME_INVALID", "Role name: 2-32 characters, lowercase letters, digits, '-' or '_'.", 422)
    if value in RESERVED_ROLE_NAMES:
        raise AppError("ROLE_NAME_RESERVED", f"'{value}' is already used by the panel or by Melorin's service access.", 422)
    return value


async def _due_for_sync(session, panel: Panel) -> None:
    """``panel_admins.sync_all`` only picks rows that are unfinished or whose profile is unsynced, so an admin that already exists would
    never learn about a new role. Flag this panel's rows: the next sync (worker, or ``sync_all``) moves each admin to the role."""
    await session.execute(update(PanelAdmin).where(PanelAdmin.panel_id == panel.id).values(profile_synced=False))


def role_body(name: str | None = None) -> dict:
    perms: dict[str, dict[str, bool]] = {}
    for path in STORE_PERMISSIONS:
        section, _, action = path.partition(".")
        perms.setdefault(section, {})[action] = True
    return {"name": normalize_role_name(name), "permissions": perms, "features": {}}


def applied_role(panel: Panel | None) -> str | None:
    cfg = (panel.config or {}) if panel is not None else {}
    role = cfg.get("admin_role") or None
    # Applied by Melorin = the default name (older installs) or any name an admin chose through apply() (flag below).
    return role if role and (role == STORE_ROLE_NAME or cfg.get("admin_role_managed")) else None


def plan(current_role: str = "operator", panel: Panel | None = None, role_name: str | None = None) -> dict:
    name = normalize_role_name(role_name or applied_role(panel))
    return {
        "applied": applied_role(panel) is not None,
        "role": name,
        "replaces": current_role,
        "grants": list(STORE_PERMISSIONS),
        "withheld": list(WITHHELD),
        "applied_by_melorin": False,
        "how": "Create the role on the panel with `body`, assign one test store admin, check a create/renew/delete round trip, then roll out.",
        "body": role_body(name),
    }


def _creds(bootstrap: dict | None) -> dict | None:
    if not bootstrap:
        return None
    if bootstrap.get("api_key"):
        return {"api_key": str(bootstrap["api_key"])}
    if bootstrap.get("username") and bootstrap.get("password"):
        return {"username": str(bootstrap["username"]), "password": str(bootstrap["password"])}
    raise AppError("BOOTSTRAP_CREDENTIAL_INVALID", "Give an owner api_key, or username and password.", 422)


async def apply(session, panel: Panel, *, bootstrap: dict | None, actor_id=None, role_name: str | None = None) -> dict:
    """Create the role on the panel, then make it the role of new / re-synced store admins. Idempotent."""
    if panel.kind != "pasarguard":
        raise AppError("NOT_PASARGUARD", "The store role is only available for PasarGuard panels.", 422)
    name = normalize_role_name(role_name or applied_role(panel))  # validated BEFORE any call to the panel
    creds = _creds(bootstrap)
    if creds is None:
        raise AppError("BOOTSTRAP_REQUIRED", "Creating a role needs an owner credential (used once, not stored).", 422)
    adapter = registry.build_adapter(panel, credentials=creds)
    try:
        try:
            role = await adapter.ensure_role(role_body(name))
        except PanelError as exc:
            detail = (getattr(exc, "message", None) or str(exc))[:200]
            raise AppError("STORE_ROLE_FAILED", f"Panel refused the role: {detail}", 502) from exc
    finally:
        await close_adapter(adapter)
    previous = (panel.config or {}).get("admin_role")
    panel.config = {**(panel.config or {}), "admin_role": name, "admin_role_managed": True}
    async with unit_of_work(session):
        await _due_for_sync(session, panel)
        audit.record(
            session,
            "panel.store_role.applied",
            actor_id=actor_id,
            actor_type="admin",
            entity_type="panel",
            entity_id=panel.id,
            data={"role": name, "role_id": role.get("id") if isinstance(role, dict) else None, "previous": previous},
        )
    return {
        "applied": True,
        "role": name,
        "previous": previous or "operator",
        "note": "New store admins get this role now; existing ones are moved to it by the next admin sync (they are flagged).",
    }


async def revert(session, panel: Panel, *, actor_id=None) -> dict:
    """Stop using the role (back to the panel's stock role). Writes nothing to the panel now; the next admin sync moves the admins back."""
    cfg = dict(panel.config or {})
    had = cfg.pop("admin_role", None)
    cfg.pop("admin_role_managed", None)
    panel.config = cfg
    async with unit_of_work(session):
        await _due_for_sync(session, panel)
        audit.record(
            session,
            "panel.store_role.reverted",
            actor_id=actor_id,
            actor_type="admin",
            entity_type="panel",
            entity_id=panel.id,
            data={"was": had},
        )
    return {"applied": False, "role": "operator"}
