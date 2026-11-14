"""One read model of "how is this panel right now" (health + live metrics + freshness), and its two siblings.

Three small models answer the whole health/capacity/attention question from one source (architecture review 2026-11-13, 4.6):

* ``PanelHealthSnapshot``     connection and node health of one panel: status, last check, last error, freshness, sellable;
* ``PanelCapacitySnapshot``   capacity of one destination (server slot): total, used, free, where the number comes from and its age;
* ``PanelOperationalIssue``   one thing that needs a person: kind, subject, status, how often it was seen.

``PanelSnapshot`` (health + the live reading of the same cycle) is what screens, reports and gauges already use; it now carries
a ``health`` view so a caller that only needs the connection never touches the reading.

The panel row stores the last health check (``health_status``, ``health_detail``, ``last_health_at``) and the last live reading
(``metrics_snapshot``, ``metrics_snapshot_at``). Both are written by the single per-panel read cycle in the worker. Every screen,
report and gauge reads them through ``PanelSnapshot`` instead of picking fields out of the row on its own. Pure: duck-typed on
the row, imports nothing of ours.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from melorin.domain.panel_health import SELLABLE_STATES


@dataclass(frozen=True)
class PanelHealthSnapshot:
    panel_id: Any
    status: str
    checked_at: dt.datetime | None
    last_error: str | None
    sellable: bool
    detail: dict = field(default_factory=dict)

    def is_fresh(self, now: dt.datetime, window: dt.timedelta) -> bool:
        return self.checked_at is not None and now - self.checked_at <= window


@dataclass(frozen=True)
class PanelCapacitySnapshot:
    server_id: Any
    capacity: int
    used: int
    source: str | None
    as_of: dt.datetime | None
    state: str
    percent: int | None
    melorin_accounts: int = 0
    panel_users: int | None = None

    @property
    def free(self) -> int:
        return max(0, self.capacity - self.used)


@dataclass(frozen=True)
class PanelOperationalIssue:
    key: str  # stable identity: ``<kind>:<subject_id>``
    kind: str
    subject_id: Any
    status: str
    occurrences: int = 1
    last_seen_at: dt.datetime | None = None

    @property
    def needs_action(self) -> bool:
        return self.status == "open"


def capacity_snapshot_of(server_id: Any, view: dict) -> PanelCapacitySnapshot:
    """Build the capacity model from the dict ``panel_integrations.capacity.capacity_view`` returns."""
    return PanelCapacitySnapshot(
        server_id=server_id,
        capacity=int(view.get("capacity") or 0),
        used=int(view.get("used") or 0),
        source=view.get("source"),
        as_of=view.get("panel_users_as_of"),
        state=str(view.get("state") or "unknown"),
        percent=view.get("percent"),
        melorin_accounts=int(view.get("melorin_accounts") or 0),
        panel_users=view.get("panel_users"),
    )


def issue_of(row: Any) -> PanelOperationalIssue:
    """Build the attention model from a ``ReconciliationIssue`` row (or anything with the same attributes)."""
    return PanelOperationalIssue(
        key=f"{row.kind}:{row.vpn_account_id}",
        kind=row.kind,
        subject_id=row.vpn_account_id,
        status=row.status,
        occurrences=int(row.occurrences or 1),
        last_seen_at=row.last_seen_at,
    )


@dataclass(frozen=True)
class PanelSnapshot:
    panel_id: Any
    name: str
    health_status: str
    checked_at: dt.datetime | None
    last_error: str | None
    sellable: bool
    detail: dict = field(default_factory=dict)
    reading: dict | None = None
    taken_at: dt.datetime | None = None

    @property
    def up(self) -> bool | None:
        return bool(self.reading.get("up")) if self.reading else None

    @property
    def users_total(self) -> Any:
        return self.reading.get("users_total") if self.reading else None

    @property
    def online_users(self) -> Any:
        return self.reading.get("online_users") if self.reading else None

    @property
    def health(self) -> PanelHealthSnapshot:
        return PanelHealthSnapshot(
            panel_id=self.panel_id,
            status=self.health_status,
            checked_at=self.checked_at,
            last_error=self.last_error,
            sellable=self.sellable,
            detail=self.detail,
        )

    def is_fresh(self, now: dt.datetime, window: dt.timedelta) -> bool:
        return self.taken_at is not None and now - self.taken_at <= window


def snapshot_of(panel: Any) -> PanelSnapshot:
    """Build the view from a ``Panel`` row (or anything with the same attributes)."""
    detail = panel.health_detail if isinstance(panel.health_detail, dict) else {}
    reading = panel.metrics_snapshot if isinstance(panel.metrics_snapshot, dict) and panel.metrics_snapshot else None
    status = panel.health_status or "unknown"
    return PanelSnapshot(
        panel_id=panel.id,
        name=panel.name,
        health_status=status,
        checked_at=panel.last_health_at,
        last_error=panel.last_health_error,
        sellable=bool(detail.get("sellable", status in SELLABLE_STATES)),
        detail=detail,
        reading=reading,
        taken_at=panel.metrics_snapshot_at,
    )
