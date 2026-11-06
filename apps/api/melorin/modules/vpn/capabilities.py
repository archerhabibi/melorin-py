"""Panel capabilities service (PG-00): probe a panel connection, store the snapshot, and answer "what can this panel do?".

``panels.capabilities`` holds ``CapabilityReport.to_dict()``. Before the first probe (or when it failed) the adapter's own static
declaration is used, so the admin UI always has an answer and never has to guess with ``getattr``."""

import datetime as dt
import logging

from melorin.core.db import utcnow
from melorin.modules.vpn.adapters import registry
from melorin.modules.vpn.adapters.base import ALL_CAPABILITIES, Capabilities, CapabilityReport, discover

log = logging.getLogger("melorin.vpn.capabilities")

REFRESH_AFTER = dt.timedelta(hours=1)


def declared_for(panel) -> Capabilities:
    """The adapter's declaration for this panel (no network, no credentials needed)."""
    cls = registry.ADAPTERS.get(panel.kind)
    if cls is None:
        return Capabilities()
    try:
        return cls(base_url=panel.base_url, credentials={}, config=panel.config or {}).capabilities()
    except Exception:
        return Capabilities()


def capabilities_of(panel) -> Capabilities:
    """Effective capabilities: the stored probe result, else the static declaration."""
    stored = getattr(panel, "capabilities", None)
    if isinstance(stored, dict) and isinstance(stored.get("flags"), dict):
        return Capabilities.from_dict(stored["flags"])
    return declared_for(panel)


def capabilities_out(panel) -> dict:
    """JSON for the admin API: always has ``flags``; ``denied``/``role``/``source`` describe a stored probe."""
    stored = getattr(panel, "capabilities", None)
    if isinstance(stored, dict) and isinstance(stored.get("flags"), dict):
        out = {**stored, "flags": {name: bool(stored["flags"].get(name)) for name in ALL_CAPABILITIES}}
    else:
        flags = declared_for(panel).to_dict()
        out = {
            "flags": flags,
            "declared": flags,
            "denied": {},
            "role": None,
            "is_owner": False,
            "users_scope": None,
            "source": "static",
            "error": None,
        }
    out["checked_at"] = panel.capabilities_checked_at.isoformat() if getattr(panel, "capabilities_checked_at", None) else None
    return out


def is_stale(panel, now: dt.datetime | None = None) -> bool:
    checked = getattr(panel, "capabilities_checked_at", None)
    if checked is None:
        return True
    checked = checked if checked.tzinfo else checked.replace(tzinfo=dt.UTC)
    return (now or utcnow()) - checked >= REFRESH_AFTER


async def probe(panel, adapter=None) -> CapabilityReport:
    """Run the probe for ``panel`` (building the adapter unless given). Never raises."""
    owned = adapter is None
    try:
        adapter = adapter or registry.build_adapter(panel)
    except Exception as exc:
        return CapabilityReport(
            capabilities=declared_for(panel),
            declared=declared_for(panel),
            source="static",
            error=(getattr(exc, "message", None) or str(exc) or exc.__class__.__name__)[:300],
        )
    try:
        return await discover(adapter)
    finally:
        if owned:
            close = getattr(adapter, "close", None)
            if callable(close):
                try:
                    await close()
                except Exception:
                    log.warning("capability probe: adapter close failed panel=%s", getattr(panel, "id", None), exc_info=True)


def store(panel, report: CapabilityReport) -> None:
    """Persist ``report``. A failed probe (``source=static`` with an error) never overwrites a good earlier probe: we keep the last
    known permissions and only note the error, so a panel outage cannot make features vanish from the UI."""
    previous = panel.capabilities if isinstance(panel.capabilities, dict) else None
    if report.source == "static" and report.error and previous and previous.get("source") == "probe":
        panel.capabilities = {**previous, "error": report.error}
    else:
        panel.capabilities = report.to_dict()
    panel.capabilities_checked_at = utcnow()


async def refresh(panel, adapter=None) -> CapabilityReport:
    report = await probe(panel, adapter)
    store(panel, report)
    return report
