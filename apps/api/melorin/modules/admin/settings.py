"""Admin API - settings routes (split from the former 1,900-line router; paths unchanged)."""

import logging
from fastapi import APIRouter
from sqlalchemy import select
from melorin.core import audit, settings_store
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError
from melorin.kernel.models.system import AuditEvent, FeatureFlag
from melorin.modules.admin.schemas import (
    FeatureUpdate,
    SettingUpdate,
)

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger("melorin.admin")


@router.get("/feature-flags")
async def list_flags(_: AdminUser, session: Session):
    return [
        {"id": f.id, "key": f.key, "scope_type": f.scope_type, "scope_id": f.scope_id, "enabled": f.enabled, "note": f.note}
        for f in (await session.scalars(select(FeatureFlag))).all()
    ]


@router.put("/feature-flags/{key}")
async def update_flag(key: str, body: FeatureUpdate, admin: AdminUser, session: Session):
    f = await session.scalar(
        select(FeatureFlag).where(FeatureFlag.key == key, FeatureFlag.scope_type == body.scope_type, FeatureFlag.scope_id == body.scope_id)
    )
    if not f:
        f = FeatureFlag(key=key, scope_type=body.scope_type, scope_id=body.scope_id)
        session.add(f)
    f.enabled, f.note = body.enabled, body.note
    audit.record(
        session,
        "feature_flag.updated",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="feature_flag",
        entity_id=f.id,
        data=body.model_dump(),
    )
    await session.commit()
    return {"ok": True}


@router.get("/settings")
async def settings(_: AdminUser, session: Session):
    return await settings_store.all_settings(session)


@router.put("/settings/{key:path}")
async def update_setting(key: str, body: SettingUpdate, admin: AdminUser, session: Session):
    if key.startswith("integration."):
        raise AppError("SETTING_RESERVED", "این تنظیم فقط از بخش یکپارچه‌سازی‌ها قابل تغییر است.", 400)
    await settings_store.set_value(session, key, body.value)
    audit.record(
        session,
        "system_setting.updated",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="system_setting",
        entity_id=key,
        data={"value": body.value},
    )
    await session.commit()
    return {"ok": True}


@router.get("/audit", response_model=list[dict])
async def audit_log(_: AdminUser, session: Session, action: str | None = None):
    q = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(500)
    if action:
        q = q.where(AuditEvent.action == action)
    return [
        {
            "id": x.id,
            "actor_id": x.actor_id,
            "action": x.action,
            "entity_type": x.entity_type,
            "entity_id": x.entity_id,
            "store_id": x.store_id,
            "data": x.data,
            "ip": x.ip,
            "created_at": x.created_at,
        }
        for x in (await session.scalars(q)).all()
    ]
