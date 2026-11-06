"""PasarGuard webhook event names (from the panel code, 5.6.0).

Phase 0 only records the vocabulary so Phase 2 (PG-03) can map events to actions in one place; ``Capabilities.event_source``
stays ``False`` until the intake endpoint, signature check and idempotent ``panel_events`` store exist."""

USER_EVENTS = (
    "user_created",
    "user_updated",
    "user_deleted",
    "user_limited",
    "user_expired",
    "user_enabled",
    "user_disabled",
    "data_usage_reset",
    "data_reset_by_next",
    "subscription_revoked",
    "reached_usage_percent",
    "reached_days_left",
)

# event -> Melorin account status it implies (None = not a status change)
EVENT_STATUS = {
    "user_limited": "limited",
    "user_expired": "expired",
    "user_enabled": "active",
    "user_disabled": "disabled",
}
