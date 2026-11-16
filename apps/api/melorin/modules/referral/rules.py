"""referral: rules (see ``service.py`` for the facade)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit, settings_store
from melorin.core.errors import AppError, NotFound
from melorin.domain.commission import Plan, PlanError, validate_plan
from melorin.kernel.models.catalog import Product, StoreProduct
from melorin.kernel.models.referral import CommissionRule
from melorin.kernel.models.stores import Store


# ---------------------------------------------------------------- plan management (one store at a time)
def rule_out(r: CommissionRule) -> dict:
    return {
        "id": r.id,
        "store_id": r.store_id,
        "product_id": r.product_id,
        "kind": r.kind,
        "model": r.model,
        "value": r.value,
        "max_amount": r.max_amount,
        "is_active": r.is_active,
    }


def _audit_view(r: CommissionRule) -> dict:
    """``rule_out`` with JSON-safe ids (the audit log stores JSON)."""
    return {k: str(v) if isinstance(v, uuid.UUID) else v for k, v in rule_out(r).items()}


async def list_rules(session: AsyncSession, store_id: uuid.UUID) -> list[CommissionRule]:
    q = select(CommissionRule).where(CommissionRule.store_id == store_id).order_by(CommissionRule.kind, CommissionRule.created_at)
    return list((await session.scalars(q)).all())


async def _check_product(session: AsyncSession, store: Store, product_id: uuid.UUID) -> None:
    """A product-specific plan must be about a product this store really sells."""
    if not await session.get(Product, product_id):
        raise NotFound("محصول")
    if store.kind == "reseller":
        offered = await session.scalar(
            select(StoreProduct.id).where(
                StoreProduct.store_id == store.id, StoreProduct.product_id == product_id, StoreProduct.is_enabled.is_(True)
            )
        )
        if not offered:
            raise AppError("REFERRAL_PRODUCT_NOT_IN_STORE", "این محصول در این فروشگاه فعال نیست.", 400)


async def upsert_rule(
    session: AsyncSession,
    store: Store,
    *,
    product_id: uuid.UUID | None,
    kind: str,
    model: str,
    value: int,
    max_amount: int | None,
    is_active: bool,
    actor_id: uuid.UUID,
    actor_type: str,
) -> CommissionRule:
    """Create or change the plan of ONE store. The caller has already proven it may act on ``store`` (Admin, or the owner
    through the owner plane); nothing here reads or writes another store's plans. The caller commits."""
    try:
        validate_plan(Plan(kind=kind, model=model, value=value, max_amount=max_amount, active=is_active))
    except PlanError as e:
        raise AppError(e.code, e.message, 400) from e
    if product_id:
        await _check_product(session, store, product_id)
    row = await session.scalar(
        select(CommissionRule).where(
            CommissionRule.store_id == store.id,
            CommissionRule.product_id.is_(None) if product_id is None else CommissionRule.product_id == product_id,
            CommissionRule.kind == kind,
        )
    )
    before = _audit_view(row) if row else None
    if not row:
        row = CommissionRule(store_id=store.id, product_id=product_id, kind=kind)
        session.add(row)
    row.model, row.value, row.max_amount, row.is_active = model, value, max_amount, is_active
    await session.flush()
    audit.record(
        session,
        "referral.rule.saved",
        actor_id=actor_id,
        actor_type=actor_type,
        entity_type="commission_rule",
        entity_id=row.id,
        store_id=store.id,
        data={"before": before, "after": _audit_view(row)},
    )
    return row


async def program_for(session: AsyncSession, store: Store) -> dict:
    """What a customer of THIS store earns by inviting friends, in plain numbers (no rule = no programme)."""
    rows = [r for r in await list_rules(session, store.id) if r.is_active and r.product_id is None]
    default = {r.kind: r for r in rows}
    out: dict = {"enabled": False, "currency": store.currency}
    for kind in ("signup_reward", "commission"):
        r = default.get(kind)
        if r and r.value > 0:
            out[kind] = {"model": r.model, "value": r.value, "max_amount": r.max_amount}
            out["enabled"] = True
    if store.kind == "main" and not out["enabled"]:  # legacy global defaults still apply to the main store only
        reward = int(await settings_store.get(session, "referral.signup_reward") or 0)
        bp = int(await settings_store.get(session, "referral.commission_bp") or 0)
        if reward > 0:
            out["signup_reward"] = {"model": "fixed", "value": reward, "max_amount": None}
        if bp > 0:
            out["commission"] = {"model": "percent", "value": bp, "max_amount": None}
        out["enabled"] = reward > 0 or bp > 0
    out["has_product_rules"] = any(r.is_active and r.product_id is not None for r in await list_rules(session, store.id))
    return out
