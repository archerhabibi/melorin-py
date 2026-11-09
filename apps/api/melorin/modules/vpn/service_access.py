"""Least-privilege service access for a PasarGuard panel (PG-05 / N4).

Today Melorin runs on the owner admin's API key: a leak would control the whole panel (nodes, admins, settings). This module moves it to
a dedicated ``melorin-service`` admin with a custom role that holds ONLY the permissions Melorin's features need
(``CAPABILITY_REQUIREMENTS`` is the single source), and manages the key's life:

* :func:`plan`       what the role will grant and what it withholds (no network, no secrets);
* :func:`provision`  create role + admin + key, VERIFY the new key really is the service role, only then switch Melorin to it;
* :func:`rotate`     same, for a replacement key, then delete the old one;
* :func:`status`     what Melorin runs on now, and the service keys the panel knows (never secret values).

Both write operations need an owner-level credential for ONE request (``bootstrap``), because the service role itself cannot create
roles or keys. It is used for that request only and never stored. The new key is stored encrypted as the panel's credential and is
never returned, logged or audited. The previous (owner) key is NOT deleted: the operator revokes it after checking the result.
"""

from __future__ import annotations

import json
import logging
import secrets

from melorin.core import audit
from melorin.core.crypto import encrypt
from melorin.core.errors import AppError
from melorin.kernel.models.vpn import Panel
from melorin.modules.vpn import capabilities as panel_caps
from melorin.modules.vpn.adapters import registry
from melorin.modules.vpn.adapters.base import PanelError
from melorin.modules.vpn.adapters.lifecycle import close_adapter
from melorin.modules.vpn.adapters.pasarguard.capabilities import CAPABILITY_REQUIREMENTS
from melorin.modules.vpn.panel_admins import generate_password

log = logging.getLogger("melorin.vpn.service_access")

ADMIN_USERNAME = "melorin-service"
ROLE_NAME = "melorin-service"
# Needed by every panel (create / renew / delete / read an account) but not tied to one optional capability.
BASE_PERMISSIONS = ("users.create", "users.read", "users.update", "users.delete", "groups.read")
# What the role deliberately does NOT hold (shown to the admin so the difference to "owner" is explicit).
WITHHELD = (
    "admins.delete",
    "nodes.create",
    "nodes.delete",
    "hosts.create",
    "groups.create",
    "groups.delete",
    "cores.create",
    "cores.delete",
    "api_keys.* (the service key cannot create or change keys)",
    "admin-role management",
)


def required_permissions() -> tuple[str, ...]:
    needed = set(BASE_PERMISSIONS)
    for perms in CAPABILITY_REQUIREMENTS.values():
        needed.update(perms)
    return tuple(sorted(needed))


def role_permissions() -> dict:
    out: dict[str, dict[str, bool]] = {}
    for path in required_permissions():
        section, _, action = path.partition(".")
        out.setdefault(section, {})[action] = True
    return out


def role_body() -> dict:
    return {
        "name": ROLE_NAME,
        "permissions": role_permissions(),
        "features": {"can_use_reset_strategy": True, "can_use_next_plan": True},
    }


def plan() -> dict:
    return {
        "admin": ADMIN_USERNAME,
        "role": ROLE_NAME,
        "grants": list(required_permissions()),
        "withheld": list(WITHHELD),
        "needs_bootstrap_credential": True,
    }


def _adapter(panel: Panel, credentials: dict | None = None):
    return registry.build_adapter(panel) if credentials is None else registry.build_adapter(panel, credentials=credentials)


def _bootstrap_credentials(bootstrap: dict | None) -> dict | None:
    if not bootstrap:
        return None
    if bootstrap.get("api_key"):
        return {"api_key": str(bootstrap["api_key"])}
    if bootstrap.get("username") and bootstrap.get("password"):
        return {"username": str(bootstrap["username"]), "password": str(bootstrap["password"])}
    raise AppError("BOOTSTRAP_CREDENTIAL_INVALID", "Give an owner api_key, or username and password.", 422)


def _fail(step: str, exc: Exception) -> AppError:
    detail = (getattr(exc, "message", None) or str(exc) or exc.__class__.__name__)[:200]
    return AppError("SERVICE_ACCESS_FAILED", f"Panel refused the step '{step}': {detail}", 502)


def _is_service_report(report) -> bool:
    """The new key is acceptable only if the panel says: probed OK, NOT owner, our role, and nothing Melorin needs is denied."""
    return bool(
        report is not None
        and report.source == "probe"
        and not report.is_owner
        and (report.role or "").lower() == ROLE_NAME
        and not report.denied
    )


async def _issue(session, panel: Panel, *, bootstrap: dict | None, actor_id, replace: bool) -> dict:
    if panel.kind != "pasarguard":
        raise AppError("NOT_PASARGUARD", "Service access is only available for PasarGuard panels.", 422)
    cfg = dict(panel.config or {})
    if replace and not cfg.get("service_key_id"):
        raise AppError("NOT_PROVISIONED", "Provision the service admin first.", 409)
    if not replace and cfg.get("service_key_id"):
        raise AppError("ALREADY_PROVISIONED", "A service key exists; use rotate to replace it.", 409)
    boot = _bootstrap_credentials(bootstrap)
    if replace and boot is None:
        raise AppError("BOOTSTRAP_REQUIRED", "Rotation needs an owner credential (used once, not stored).", 422)
    owner = _adapter(panel, boot)
    candidate = None
    new_key: dict | None = None
    try:
        try:
            await owner.ensure_role(role_body())
            admin = await owner.ensure_admin(
                ADMIN_USERNAME, generate_password() + generate_password(), role=ROLE_NAME
            )  # thrown away: key only; meets the panel's password rule (found live: token_urlsafe sometimes had no special character -> 422)
            admin_id = int(admin["id"])
            new_key = await owner.create_api_key(admin_id, f"melorin-service-{secrets.token_hex(3)}", "Managed by Melorin (PG-05)")
        except PanelError as exc:
            raise _fail("create role/admin/key", exc) from exc
        secret = str(new_key.get("api_key") or "")
        if not secret:
            raise AppError("SERVICE_ACCESS_FAILED", "Panel did not return a key value.", 502)
        candidate = _adapter(panel, {"api_key": secret})
        report = await panel_caps.probe(panel, candidate)
        if not _is_service_report(report):
            await _drop_key(owner, new_key)
            denied = sorted({p for perms in (report.denied or {}).values() for p in perms}) if report else []
            raise AppError(
                "SERVICE_KEY_REJECTED",
                "The new key did not verify as the least-privilege service role; Melorin was NOT switched. "
                f"role={getattr(report, 'role', None)} owner={getattr(report, 'is_owner', None)} missing={denied}",
                409,
            )
        old_key_id = cfg.get("service_key_id")
        panel.credentials_enc = encrypt(json.dumps({"api_key": secret}))
        cfg.update({"service_admin_id": admin_id, "service_key_id": int(new_key["id"])})
        panel.config = cfg
        panel_caps.store(panel, report)
        deleted_old = False
        if replace and old_key_id:
            try:
                await owner.delete_api_key(int(old_key_id))
                deleted_old = True
            except PanelError:
                log.warning("service access: old key not deleted panel=%s key=%s", panel.id, old_key_id, exc_info=True)
        audit.record(
            session,
            "panel.service_access.rotated" if replace else "panel.service_access.provisioned",
            actor_id=actor_id,
            actor_type="admin",
            entity_type="panel",
            entity_id=panel.id,
            data={"admin_id": admin_id, "key_id": int(new_key["id"]), "role": ROLE_NAME, "old_key_deleted": deleted_old},
        )
        await session.commit()
        return {
            "switched": True,
            "role": ROLE_NAME,
            "admin": ADMIN_USERNAME,
            "key_id": int(new_key["id"]),
            "old_key_deleted": deleted_old,
            "next_step": None
            if replace
            else "Melorin now runs on the service key. Revoke the previous owner API key on the panel once you have checked the panel page.",
        }
    finally:
        await close_adapter(owner)
        if candidate is not None:
            await close_adapter(candidate)


async def _drop_key(owner, key: dict | None) -> None:
    if key and key.get("id") is not None:
        try:
            await owner.delete_api_key(int(key["id"]))
        except PanelError:
            log.warning("service access: could not remove rejected key id=%s", key.get("id"), exc_info=True)


async def provision(session, panel: Panel, *, bootstrap: dict | None = None, actor_id=None) -> dict:
    """First switch. ``bootstrap`` omitted = use the credential stored on the panel (it must be owner-level to create roles/keys)."""
    return await _issue(session, panel, bootstrap=bootstrap, actor_id=actor_id, replace=False)


async def rotate(session, panel: Panel, *, bootstrap: dict, actor_id=None) -> dict:
    return await _issue(session, panel, bootstrap=bootstrap, actor_id=actor_id, replace=True)


async def status(panel: Panel, *, bootstrap: dict | None = None) -> dict:
    """No network unless ``bootstrap`` is given (then the panel's service keys are listed: name, status, request count - no values)."""
    review = panel_caps.access_review(panel)
    cfg = panel.config or {}
    out = {
        "level": review["level"],
        "role": review["role"],
        "warnings": review["warnings"],
        "provisioned": bool(cfg.get("service_key_id")),
        "service_admin_id": cfg.get("service_admin_id"),
        "service_key_id": cfg.get("service_key_id"),
        "plan": plan(),
        "keys": None,
    }
    boot = _bootstrap_credentials(bootstrap)
    if boot is not None and cfg.get("service_admin_id"):
        adapter = _adapter(panel, boot)
        try:
            rows = await adapter.list_api_keys(int(cfg["service_admin_id"]))
            out["keys"] = [
                {k: r.get(k) for k in ("id", "name", "status", "created_at", "expire_date", "request_count", "api_key_trimmed")}
                for r in rows
            ]
        except PanelError as exc:
            raise _fail("list keys", exc) from exc
        finally:
            await close_adapter(adapter)
    return out
