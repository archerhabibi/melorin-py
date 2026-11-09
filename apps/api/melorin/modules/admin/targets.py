"""Admin API - destinations (مقصد): what a panel offers (groups, templates, inbounds) and server slots built from them.

A server (UI: مقصد) is one panel plus one target plus a capacity. This module lists what the panel really has, checks a
stored target against it (warnings, never a blocker: a panel that is down must not stop an admin from saving) and creates
many slots at once (wizard / sync with the panel).
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from melorin.modules.vpn.adapters import providers
from melorin.core import audit
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError, NotFound
from melorin.kernel.models.vpn import Panel, Server
from melorin.modules.panelops import queries
from melorin.modules.vpn.panel_session import close_adapter
from melorin.modules.vpn.adapters.registry import build_adapter
from melorin.modules.vpn.targets import normalize_target, validate_target

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger("melorin.admin.targets")

DEFAULT_CAPACITY = 500  # the value every group has today; editable per destination afterwards


def api_style(panel: Panel) -> str | None:
    return (panel.config or {}).get("api_style")


def check_target(panel: Panel, target: dict | None) -> dict | None:
    """Normalise and validate a target for ``panel``. Raises a 422 with every problem; returns the stored form (None = inherit)."""
    stored = normalize_target(target)
    problems = validate_target(panel.kind, stored, api_style=api_style(panel))
    if problems:
        raise AppError("INVALID_TARGET", "؛ ".join(problems), 422, {"errors": problems})
    return stored


async def fetch_listing(panel: Panel) -> dict | None:
    """What the panel offers right now, or None when it cannot be asked (down, wrong credentials, kind without a listing)."""
    adapter = None
    try:
        adapter = build_adapter(panel)
        lister = getattr(adapter, "list_targets", None)
        return await lister() if callable(lister) else None
    except Exception:
        log.info("panel target listing failed panel=%s", panel.id, exc_info=True)
        return None
    finally:
        await close_adapter(adapter)


def listing_warnings(panel: Panel, target: dict | None, listing: dict | None) -> list[str]:
    """Compare ``target`` with the panel's own listing. Only warnings: the panel may change after saving."""
    if not target:
        return []
    if listing is None:
        return ["پنل در دسترس نیست یا فهرست مقصد ندارد؛ وجود مقصد روی پنل بررسی نشد."]
    return providers.target_warnings(panel.kind, target, listing)


async def duplicate_warning(session, panel: Panel, target: dict | None, *, exclude: uuid.UUID | None = None) -> list[str]:
    """Two slots on one panel aimed at the same destination count the same users twice: say so."""
    if not target:
        return []
    rows = await queries.servers_of_panel(session, panel.id)
    same = [s.name for s in rows if s.id != exclude and normalize_target(s.target) == target]
    return [f"مقصد دیگری روی همین پنل (همین گروه/اینباند) وجود دارد: {', '.join(same)}"] if same else []


async def target_warnings(session, panel: Panel, target: dict | None, *, exclude: uuid.UUID | None = None) -> list[str]:
    if not target:
        return []
    listing = await fetch_listing(panel)
    return [*listing_warnings(panel, target, listing), *await duplicate_warning(session, panel, target, exclude=exclude)]


@router.get("/panels/{panel_id}/targets")
async def panel_targets(panel_id: uuid.UUID, _: AdminUser, session: Session):
    """The panel's own groups/templates (PasarGuard) or inbounds (Sanaei), each marked with the servers already using it."""
    panel = await session.get(Panel, panel_id)
    if not panel:
        raise NotFound("پنل")
    listing = await fetch_listing(panel)
    if listing is None:
        raise AppError("TARGETS_UNAVAILABLE", "فهرست گروه/اینباند از پنل خوانده نشد (پنل در دسترس نیست یا پشتیبانی نمی‌کند).", 502)
    servers = await queries.servers_of_panel(session, panel.id)

    def used(key: str, value: int) -> list[dict]:
        out = []
        for s in servers:
            t = normalize_target(s.target) or {}
            have = t.get(key)
            if (isinstance(have, list) and value in have) or (not isinstance(have, list) and have == value):
                out.append({"id": str(s.id), "name": s.name})
        return out

    from melorin.modules.admin.capacity import (
        live_group_health,
    )  # PG-08: each group with its real state (a broken one is flagged, not hidden)

    health = await live_group_health(panel) or {}
    for g in listing.get("groups", []):
        g["health"] = health.get(g["id"])
        g["used_by"] = used("group_ids", g["id"])
    for t in listing.get("templates", []):
        t["used_by"] = used("user_template_id", t["id"])
    for i in listing.get("inbounds", []):
        i["used_by"] = used("inbound_ids", i["id"])
    return {"panel_id": panel.id, "panel_kind": panel.kind, "capacity_default": DEFAULT_CAPACITY, **listing}


class ServersFromTargets(BaseModel):
    """Wizard / sync: one server slot per chosen group, template or inbound (or per ``set`` of inbounds)."""

    kind: str = Field(pattern="^(group|template|inbound)$")
    ids: list[int] = Field(min_length=1, max_length=200)
    capacity: int = Field(default=DEFAULT_CAPACITY, gt=0, le=100000)
    allow_test: bool = True
    product_codes: list[str] | None = None
    limits_from: str | None = Field(default=None, pattern="^(product|template)$")  # templates only
    group_as_one: bool = False  # inbound only: put ALL chosen inbounds in ONE slot (a set) instead of one slot each


def _target_for(kind: str, value: list[int] | int, limits_from: str | None) -> dict:
    if kind == "group":
        return {"group_ids": [value]}
    if kind == "template":
        return {"user_template_id": value, **({"limits_from": limits_from} if limits_from else {})}
    return {"inbound_ids": value if isinstance(value, list) else [value]}


@router.post("/panels/{panel_id}/servers/from-targets", status_code=201)
async def create_servers_from_targets(panel_id: uuid.UUID, body: ServersFromTargets, admin: AdminUser, session: Session):
    from melorin.modules.admin.panels import _clean_product_codes  # same product-code rule as a single server

    panel = await session.get(Panel, panel_id)
    if not panel:
        raise NotFound("پنل")
    if body.kind in ("group", "template") and body.kind not in providers.target_kinds(panel.kind):
        raise AppError("INVALID_TARGET", "گروه و تمپلیت فقط برای پنل پاسارگارد است.", 422)
    if body.kind == "inbound" and "inbound" not in providers.target_kinds(panel.kind):
        raise AppError("INVALID_TARGET", "اینباند فقط برای پنل سنایی است.", 422)
    codes = await _clean_product_codes(session, body.product_codes)
    listing = await fetch_listing(panel) or {}
    names = {
        "group": {g["id"]: g["name"] for g in listing.get("groups", [])},
        "template": {t["id"]: t["name"] for t in listing.get("templates", [])},
        "inbound": {i["id"]: (i.get("remark") or f"inbound {i['id']}") for i in listing.get("inbounds", [])},
    }[body.kind]
    label = {"group": "گروه", "template": "تمپلیت", "inbound": "اینباند"}[body.kind]

    units: list[list[int] | int] = (
        [list(dict.fromkeys(body.ids))] if (body.kind == "inbound" and body.group_as_one) else list(dict.fromkeys(body.ids))
    )
    existing = [normalize_target(s.target) for s in await queries.servers_of_panel(session, panel.id)]
    created, skipped = [], []
    for unit in units:
        target = check_target(panel, _target_for(body.kind, unit, body.limits_from))
        if target in existing:
            skipped.append({"target": target, "reason": "برای این مقصد قبلاً سرور ساخته شده است."})
            continue
        ids = unit if isinstance(unit, list) else [unit]
        title = " + ".join(str(names.get(i, i)) for i in ids)
        server = Server(
            name=f"{panel.name} · {label} {title}"[:100],
            panel_id=panel.id,
            capacity=body.capacity,
            allow_test=body.allow_test,
            product_codes=codes,
            target=target,
        )
        session.add(server)
        await session.flush()
        existing.append(target)
        created.append({"id": server.id, "name": server.name, "target": target})
        audit.record(
            session,
            "server.created",
            actor_id=admin.id,
            actor_type="admin",
            entity_type="server",
            entity_id=server.id,
            data={"via": "from_targets", "target": target},
        )
    await session.commit()
    return {"created": created, "skipped": skipped}
