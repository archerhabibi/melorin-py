"""One read model of "how is this panel right now" (health + live metrics + freshness).

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
