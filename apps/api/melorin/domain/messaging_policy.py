"""Which notification goes to whom, on which channel, how loudly (architecture review 2026-11-13, sections 4.7 and 5).

The delivery paths stay separate (outbox -> Telegram DM, Event Center topics, Alertmanager, VPN notices); this table is the one place that
says what each KIND of message is. Rules: technical alerts never go to customers; commercial notices never go to the technical topics;
the dedup key is always ``event_id + recipient + channel`` (see ``notification_dedup``). Pure, imports nothing of ours.
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


# Longest matching prefix wins; anything unknown is a commercial info message to the customer (the historical behaviour).
_ROUTES: dict[str, Route] = {
    "provisioning_failed": Route(TECHNICAL, CRITICAL, ADMINS, (DM, EVENT_CENTER)),
    "outbox_failure": Route(TECHNICAL, CRITICAL, ADMINS, (EVENT_CENTER,)),
    "panel_": Route(TECHNICAL, WARNING, ADMINS, (EVENT_CENTER,)),
    "backup_": Route(TECHNICAL, WARNING, ADMINS, (EVENT_CENTER,)),
    "infra_": Route(TECHNICAL, WARNING, ADMINS, (EVENT_CENTER,)),
    "vpn_near_expiry": Route(COMMERCIAL, INFO, CUSTOMER, (DM,)),
    "vpn_expired": Route(COMMERCIAL, WARNING, CUSTOMER, (DM,)),
    "store_volume_": Route(COMMERCIAL, WARNING, STORE_OWNER, (DM, EVENT_CENTER)),
}
_DEFAULT = Route(COMMERCIAL, INFO, CUSTOMER, (DM,))


def route_for(kind: str | None) -> Route:
    k = kind or ""
    best = max((p for p in _ROUTES if k.startswith(p)), key=len, default=None)
    return _ROUTES[best] if best else _DEFAULT


def allowed(kind: str | None, audience: str, channel: str) -> bool:
    """May a message of this kind be sent to this audience on this channel?"""
    r = route_for(kind)
    if r.family == TECHNICAL and audience == CUSTOMER:
        return False
    return audience == r.audience and channel in r.channels
