"""Notification dedup key: ``event_id + recipient + channel`` (architecture review 2026-11-13, section 4.7).

An outbox retry re-runs the handler with the same event id, so the same recipient on the same channel is never notified
twice, while the same event may still reach the same person on ANOTHER channel. Explicit domain keys keep winning.
"""

EVENT_ID_FIELD = "_event_id"


def notification_key(event_id: str, recipient: str, channel: str) -> str:
    return f"ev:{event_id}:{recipient}:{channel}"[:200]


def effective_key(payload: dict, recipient: str, channel: str) -> str | None:
    """The key to dedupe on: the payload's own ``dedup_key`` if any, else one derived from the outbox event id; None outside the outbox."""
    explicit = payload.get("dedup_key")
    if explicit:
        return explicit
    event_id = payload.get(EVENT_ID_FIELD)
    return notification_key(str(event_id), recipient, channel) if event_id else None
