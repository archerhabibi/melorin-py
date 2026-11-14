"""Admin API - panel user templates and plan change (PG-09).

``GET    /admin/panels/{id}/templates``                      templates on the panel next to the packages mapped to them (+ drift)
``POST   /admin/panels/{id}/templates``                      create the package's template on the panel and map it (idempotent)
``POST   /admin/panels/{id}/templates/link``                 map a package to a template that already exists (never edited by Melorin)
``POST   /admin/panels/{id}/templates/{product_id}/sync``    rewrite a Melorin-created template to the package's current numbers
``POST   /admin/panels/{id}/templates/{product_id}/disable`` / ``enable``
``DELETE /admin/panels/{id}/templates/{product_id}``         forget the mapping (the template stays on the panel)
``POST   /admin/vpn-accounts/{account_id}/change-plan``      move an existing account to another package's template (reason required)

All admin-only and audited; rules live in :mod:`melorin.modules.panel_integrations.templates` and :mod:`melorin.modules.vpn_accounts.plans`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from melorin.core.deps import AdminUser, Session
from melorin.core.errors import NotFound
from melorin.kernel.models.catalog import Product
from melorin.kernel.models.vpn import Panel, VpnAccount
from melorin.modules.vpn_accounts import live, plans
from melorin.modules.panel_integrations import templates

router = APIRouter(prefix="/admin", tags=["admin"])


class TemplateCreateIn(BaseModel):
    product_id: uuid.UUID
    group_ids: list[int] | None = Field(default=None, max_length=templates.MAX_GROUPS)  # None = the panel's own configured groups


class TemplateLinkIn(BaseModel):
    product_id: uuid.UUID
    remote_template_id: int = Field(gt=0)


class ChangePlanIn(BaseModel):
    product_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=300)


async def _panel(session, panel_id: uuid.UUID) -> Panel:
    panel = await session.get(Panel, panel_id)
    if not panel:
        raise NotFound("پنل")
    return panel


async def _product(session, product_id: uuid.UUID) -> Product:
    product = await session.get(Product, product_id)
    if not product:
        raise NotFound("پکیج")
    return product


def _row(r) -> dict:
    return {"product_id": r.product_id, "remote_template_id": r.remote_template_id, "name": r.name, "managed": r.managed}


@router.get("/panels/{panel_id}/templates")
async def panel_templates(panel_id: uuid.UUID, _: AdminUser, session: Session):
    return await templates.overview(session, await _panel(session, panel_id))


@router.post("/panels/{panel_id}/templates", status_code=201)
async def template_create(panel_id: uuid.UUID, body: TemplateCreateIn, admin: AdminUser, session: Session):
    panel, product = await _panel(session, panel_id), None
    product = await _product(session, body.product_id)
    return _row(await templates.create_for_product(session, panel, product, admin_id=admin.id, group_ids=body.group_ids))


@router.post("/panels/{panel_id}/templates/link")
async def template_link(panel_id: uuid.UUID, body: TemplateLinkIn, admin: AdminUser, session: Session):
    panel = await _panel(session, panel_id)
    product = await _product(session, body.product_id)
    return _row(await templates.link_existing(session, panel, product, body.remote_template_id, admin_id=admin.id))


@router.post("/panels/{panel_id}/templates/{product_id}/sync")
async def template_sync(panel_id: uuid.UUID, product_id: uuid.UUID, admin: AdminUser, session: Session):
    return await templates.sync_product(session, await _panel(session, panel_id), await _product(session, product_id), admin_id=admin.id)


@router.post("/panels/{panel_id}/templates/{product_id}/disable", status_code=204)
async def template_disable(panel_id: uuid.UUID, product_id: uuid.UUID, admin: AdminUser, session: Session):
    await templates.set_disabled(session, await _panel(session, panel_id), await _product(session, product_id), True, admin_id=admin.id)


@router.post("/panels/{panel_id}/templates/{product_id}/enable", status_code=204)
async def template_enable(panel_id: uuid.UUID, product_id: uuid.UUID, admin: AdminUser, session: Session):
    await templates.set_disabled(session, await _panel(session, panel_id), await _product(session, product_id), False, admin_id=admin.id)


@router.delete("/panels/{panel_id}/templates/{product_id}", status_code=204)
async def template_unlink(panel_id: uuid.UUID, product_id: uuid.UUID, admin: AdminUser, session: Session):
    await templates.unlink(session, await _panel(session, panel_id), await _product(session, product_id), admin_id=admin.id)


@router.post("/vpn-accounts/{account_id}/change-plan")
async def change_plan(account_id: uuid.UUID, body: ChangePlanIn, admin: AdminUser, session: Session):
    account = await session.get(VpnAccount, account_id)
    if account is None:
        raise NotFound("اکانت VPN")
    product = await _product(session, body.product_id)
    return await live.card(session, await plans.change_plan(session, account, product, admin_id=admin.id, reason=body.reason))
