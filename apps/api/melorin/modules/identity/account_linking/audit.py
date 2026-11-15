"""Append-only audit trail of linking operations (``account_link_audits``) next to the platform AuditEvent."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit as platform_audit
from melorin.kernel.models.person import AccountLinkAudit


def log(
    session: AsyncSession,
    action: str,
    *,
    person_id: uuid.UUID | None,
    actor_id: uuid.UUID | None = None,
    actor_type: str = "user",
    operation_id: uuid.UUID | None = None,
    before: dict | None = None,
    after: dict | None = None,
    reason: str | None = None,
) -> None:
    session.add(
        AccountLinkAudit(
            person_id=person_id,
            action=action,
            actor_id=actor_id,
            actor_type=actor_type,
            operation_id=operation_id,
            before=before,
            after=after,
            reason=(reason or None) and reason[:500],
        )
    )
    platform_audit.record(
        session,
        f"account_link.{action}",
        actor_id=actor_id,
        actor_type=actor_type,
        entity_type="person",
        entity_id=person_id,
        data={"operation_id": str(operation_id) if operation_id else None, "reason": reason},
    )
