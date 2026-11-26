"""Which notification goes to whom, on which channel, how loudly (architecture review 2026-11-13, sections 4.7 and 5).

There are two kinds of notice:

* **Personal notices** (a customer, a store owner, an applicant): a DM to that person through ``notification.send``.
* **Admin notices** (what the platform admin should know about): ONE rule decides where they go (2026-11-26).
  The admin's bot DM is reserved for **panel / node failures** and **customers' payments**; every other admin notice lands in a
  Topic of the admin's Telegram supergroup (the Event Center). A DM kind is mirrored in the group too, so the group stays the
  complete, orderly journal and the DM is only the "look now" ping.

This table is the one place that says what each KIND of message is; call sites state the kind and never choose a channel. A kind the
table does not know is a quiet group notice, so a new notice type can never start pinging the admin by accident. Technical alerts never go
to customers; commercial notices never go to the technical topics; the dedup key is always ``event_id + recipient + channel`` (see
``notification_dedup``). Pure, imports nothing of ours (the Topic keys below are checked against ``eventcenter.topics`` by a test).
"""

from __future__ import annotations

from dataclasses import dataclass

TECHNICAL, COMMERCIAL = "technical", "commercial"
INFO, WARNING, CRITICAL = "info", "warning", "critical"
ADMINS, CUSTOMER, STORE_OWNER = "admins", "customer", "store_owner"
DM, EVENT_CENTER = "dm", "event_center"


@dataclass(frozen=True)
class Route:
    family: str
    severity: str
    audience: str
    channels: tuple[str, ...]
    topic: str | None = None  # the Event Center Topic key of an admin notice (None for a personal notice)


# Longest matching prefix wins; anything unknown is a commercial info message to the customer (the historical behaviour).
_ROUTES: dict[str, Route] = {
    # --- admin notices that also reach the admin's bot DM: panel/node failures and customers' payments, nothing else ---
    "panel_unhealthy": Route(TECHNICAL, CRITICAL, ADMINS, (DM, EVENT_CENTER), "panels"),
    "node_failed": Route(TECHNICAL, CRITICAL, ADMINS, (DM, EVENT_CENTER), "panels"),
    "payment_succeeded": Route(COMMERCIAL, INFO, ADMINS, (DM, EVENT_CENTER), "payments"),
    "payment_receipt_review": Route(COMMERCIAL, WARNING, ADMINS, (DM, EVENT_CENTER), "payments"),
    "payment_grace_credited": Route(COMMERCIAL, WARNING, ADMINS, (DM, EVENT_CENTER), "payments"),
    # --- admin notices that only go to the supergroup ---
    "panel_": Route(TECHNICAL, WARNING, ADMINS, (EVENT_CENTER,), "panels"),  # recovered, degraded, settings drift, capacity
    "node_": Route(TECHNICAL, INFO, ADMINS, (EVENT_CENTER,), "panels"),  # a node that is back
    "payment_": Route(COMMERCIAL, INFO, ADMINS, (EVENT_CENTER,), "payments"),  # failed, bank-SMS notes, blocked auto-approval
    "provisioning_failed": Route(TECHNICAL, CRITICAL, ADMINS, (EVENT_CENTER,), "errors"),
    "outbox_failure": Route(TECHNICAL, CRITICAL, ADMINS, (EVENT_CENTER,), "errors"),
    "backup_": Route(TECHNICAL, WARNING, ADMINS, (EVENT_CENTER,), "backup"),
    "infra_": Route(TECHNICAL, WARNING, ADMINS, (EVENT_CENTER,), "errors"),
    "admin_": Route(COMMERCIAL, INFO, ADMINS, (EVENT_CENTER,), "admin"),  # reseller applications, manual set-up tasks
    # --- personal notices ---
    "vpn_near_expiry": Route(COMMERCIAL, INFO, CUSTOMER, (DM,)),
    "vpn_expired": Route(COMMERCIAL, WARNING, CUSTOMER, (DM,)),
    "store_volume_": Route(COMMERCIAL, WARNING, STORE_OWNER, (DM, EVENT_CENTER)),
}
_DEFAULT = Route(COMMERCIAL, INFO, CUSTOMER, (DM,))
_ADMIN_DEFAULT = Route(COMMERCIAL, INFO, ADMINS, (EVENT_CENTER,), "admin")

# The admin kinds that reach the bot DM. A test pins this set: widening it is a product decision, not a side effect.
ADMIN_DM_KINDS = frozenset(k for k, r in _ROUTES.items() if r.audience == ADMINS and DM in r.channels)


def route_for(kind: str | None) -> Route:
    k = kind or ""
    best = max((p for p in _ROUTES if k.startswith(p)), key=len, default=None)
    return _ROUTES[best] if best else _DEFAULT


def admin_route(kind: str | None) -> Route:
    """The route of an ADMIN notice. A kind the table does not know (or a personal kind) is a quiet notice in the group's admin Topic."""
    r = route_for(kind)
    return r if r.audience == ADMINS else _ADMIN_DEFAULT


def admin_dm(kind: str | None) -> bool:
    """Does this admin notice also go to the admin's bot DM? True only for panel/node failures and customers' payments."""
    return DM in admin_route(kind).channels


def allowed(kind: str | None, audience: str, channel: str) -> bool:
    """May a message of this kind be sent to this audience on this channel?"""
    r = route_for(kind)
    if r.family == TECHNICAL and audience == CUSTOMER:
        return False
    return audience == r.audience and channel in r.channels


def dm_allowed(kind: str | None) -> bool:
    """May this kind be delivered as a Telegram DM at all? Kinds routed only to the Event Center (panel recovery, backup, provisioning
    failures, reseller applications ...) are not: this is also the safety net if a call site still sends one as a personal notice."""
    return DM in route_for(kind).channels
