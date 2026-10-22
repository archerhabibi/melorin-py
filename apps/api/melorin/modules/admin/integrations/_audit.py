"""One audit-trail entry per integration change/test; every integration route records it the same way."""

from melorin.core import audit


def record_integration(session, admin, action: str, name: str, data: dict) -> None:
    """Queue ``integration.<action>`` for ``<name>`` (the caller commits together with the change itself)."""
    audit.record(
        session,
        f"integration.{action}",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="integration",
        entity_id=name,
        data=data,
    )
