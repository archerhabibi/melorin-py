import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.context import client_ip, correlation_id
from melorin.kernel.models.system import AuditEvent, SecurityEvent


def record(
    session: AsyncSession,
    action: str,
    *,
    actor_id: uuid.UUID | None = None,
    actor_type: str = "user",
    entity_type: str | None = None,
    entity_id: object | None = None,
    store_id: uuid.UUID | None = None,
    data: dict | None = None,
) -> None:
    """Queue an audit event in the current transaction (committed atomically with the change)."""
    session.add(
        AuditEvent(
            actor_id=actor_id,
            actor_type=actor_type,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            store_id=store_id,
            data=data,
            ip=client_ip.get(),
            correlation_id=correlation_id.get(),
        )
    )


def security_event(session: AsyncSession, kind: str, user_id: uuid.UUID | None = None, data: dict | None = None) -> None:
    session.add(SecurityEvent(kind=kind, user_id=user_id, ip=client_ip.get(), data=data))
