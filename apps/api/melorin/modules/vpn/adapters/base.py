"""Standard Panel Adapter interface (doc 03). Every panel gets its own adapter + contract tests."""

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

GB = 1024**3


class ErrorKind(StrEnum):
    TRANSIENT = "transient"  # timeouts, 5xx: retry with backoff
    PERMANENT = "permanent"  # 4xx validation: manual review
    UNKNOWN = "unknown"  # outcome unclear: check panel state before retrying


class PanelError(Exception):
    def __init__(self, kind: ErrorKind, message: str):
        super().__init__(message)
        self.kind, self.message = kind, message


@dataclass
class AccountSpec:
    username: str
    expire_at: dt.datetime | None
    traffic_bytes: int  # 0 = unlimited
    max_devices: int | None = None
    note: str | None = None
    owner: str | None = None  # panel admin that must own the new account (PasarGuard: the store's Operator admin)


@dataclass
class PanelAccount:
    ref: str
    username: str
    status: str  # normalized: active | disabled | expired | limited | unknown
    expire_at: dt.datetime | None
    traffic_limit_bytes: int
    traffic_used_bytes: int
    subscription_url: str | None = None
    links: list[str] = field(default_factory=list)
    # PG-02: what the panel itself says (None = this panel kind does not report it). ``status`` above is the normalised view.
    remote_status: str | None = None  # raw panel status, e.g. PasarGuard ``on_hold``
    online_at: dt.datetime | None = None
    lifetime_used_bytes: int | None = None
    owner: str | None = None  # panel admin that owns the account (PasarGuard ``admin.username``)


# Capability names, in display order. ``Capabilities`` fields, ``panels.capabilities`` JSON keys and the admin UI all use these.
CORE_CAPABILITIES = ("suspend", "extend", "subscription_url", "traffic_reset")
OPTIONAL_CAPABILITIES = (
    "subscription_rotate",  # new subscription link (``rotate_subscription``)
    "node_ops",  # NodeOps: list/inspect nodes (read-only)
    "node_control",  # NodeOps: reconnect a node (changes panel state)
    "usage_ops",  # UsageOps: per-account usage history
    "device_ops",  # DeviceOps: list/delete/reset HWID devices
    "bulk_ops",  # BulkOps: chunked operations over many accounts
    "admin_ops",  # AdminOps: panel-side admin (store operator) management
    "settings_ops",  # SettingsOps: read panel settings
    "account_listing",  # AccountListing: page through every account of the panel (reconcile v2, orphan discovery)
    "event_source",  # EventSource: the panel pushes webhooks to Melorin
)
ALL_CAPABILITIES = CORE_CAPABILITIES + OPTIONAL_CAPABILITIES


@dataclass
class Capabilities:
    """What an adapter (and, after a permission probe, the credential it holds) can do.

    The first four flags are the original contract every adapter reports. The optional flags default to ``False``: an adapter
    opts in per feature, so Sanaei / upstream_bot / mock need no change and callers never guess with ``getattr``."""

    suspend: bool = True
    extend: bool = True
    subscription_url: bool = True
    traffic_reset: bool = False
    subscription_rotate: bool = False
    node_ops: bool = False
    node_control: bool = False
    usage_ops: bool = False
    device_ops: bool = False
    bulk_ops: bool = False
    admin_ops: bool = False
    settings_ops: bool = False
    account_listing: bool = False
    event_source: bool = False

    def to_dict(self) -> dict[str, bool]:
        return {name: bool(getattr(self, name)) for name in ALL_CAPABILITIES}

    @classmethod
    def from_dict(cls, data: dict | None) -> "Capabilities":
        """Tolerant loader for ``panels.capabilities``: unknown keys are ignored, missing keys keep their default."""
        known = {name: bool(data[name]) for name in ALL_CAPABILITIES if isinstance(data, dict) and name in data}
        return cls(**known)

    def enabled(self) -> list[str]:
        return [name for name in ALL_CAPABILITIES if getattr(self, name)]

    def has(self, name: str) -> bool:
        return name in ALL_CAPABILITIES and bool(getattr(self, name))

    def restricted_to(self, allowed: "Capabilities | dict | None") -> "Capabilities":
        """Intersection: what the adapter supports AND the credential may do."""
        other = allowed if isinstance(allowed, Capabilities) else Capabilities.from_dict(allowed)
        return Capabilities(**{name: getattr(self, name) and getattr(other, name) for name in ALL_CAPABILITIES})


@dataclass
class CapabilityReport:
    """Result of probing one panel connection: what the adapter supports, what this credential may actually do, and why not.

    ``capabilities`` is the EFFECTIVE set (declared AND permitted) and is what ``panels.capabilities`` stores and the UI reads.
    ``denied`` maps a declared-but-unusable capability to the permissions the credential lacks (e.g. ``{"node_ops": ["nodes.read"]}``).
    ``source`` is ``probe`` when the panel's role was read, ``static`` when only the adapter's own declaration is known."""

    capabilities: Capabilities
    declared: Capabilities
    denied: dict[str, list[str]] = field(default_factory=dict)
    role: str | None = None
    is_owner: bool = False
    users_scope: int | None = None  # PasarGuard permission scope: 0 none, 1 own users only, 2 all users
    source: str = "static"
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "flags": self.capabilities.to_dict(),
            "declared": self.declared.to_dict(),
            "denied": {k: list(v) for k, v in sorted(self.denied.items())},
            "role": self.role,
            "is_owner": self.is_owner,
            "users_scope": self.users_scope,
            "source": self.source,
            "error": self.error,
        }


def static_report(adapter, *, error: str | None = None) -> CapabilityReport:
    """Report for adapters that cannot (or need not) probe permissions: the declaration is the truth."""
    caps = adapter.capabilities()
    return CapabilityReport(capabilities=caps, declared=caps, source="static", error=error)


async def discover(adapter) -> CapabilityReport:
    """Probe ``adapter`` if it knows how (``discover_capabilities``), otherwise report its static declaration. Never raises."""
    probe = getattr(adapter, "discover_capabilities", None)
    if callable(probe):
        try:
            return await probe()
        except Exception as exc:  # a probe failure must not break panel registration or the health job
            return static_report(adapter, error=(getattr(exc, "message", None) or str(exc) or exc.__class__.__name__)[:300])
    return static_report(adapter)


# --- Optional operation groups (PG-00). An adapter implements a group's methods AND sets the matching Capabilities flag. ---
@runtime_checkable
class NodeOps(Protocol):  # flags: node_ops (read), node_control (reconnect)
    async def list_nodes(self) -> list[dict]: ...
    async def get_node(self, node_id: int) -> dict | None: ...
    async def reconnect_node(self, node_id: int) -> None: ...


@runtime_checkable
class UsageOps(Protocol):  # flag: usage_ops
    async def get_usage(
        self, username: str, *, start: dt.datetime | None = None, end: dt.datetime | None = None, period: str = "day"
    ) -> list[dict]: ...


@runtime_checkable
class DeviceOps(Protocol):  # flag: device_ops
    async def list_devices(self, username: str) -> list[dict]: ...
    async def delete_device(self, username: str, hwid: str) -> None: ...
    async def reset_devices(self, username: str) -> None: ...


@runtime_checkable
class BulkOps(Protocol):  # flag: bulk_ops
    async def bulk_set_owner(self, refs: list[str], owner: str) -> int: ...


@runtime_checkable
class AdminOps(Protocol):  # flag: admin_ops
    async def find_admin(self, username: str) -> dict | None: ...
    async def ensure_admin(self, username: str, password: str, *, role: str = "operator", profile: dict | None = None) -> dict: ...
    async def update_admin_profile(self, remote_id: int, profile: dict, *, password: str | None = None) -> dict: ...


@runtime_checkable
class SettingsOps(Protocol):  # flag: settings_ops (read-only in Phase 0)
    async def get_settings(self) -> dict: ...


@runtime_checkable
class AccountListing(Protocol):  # flag: account_listing (PG-04)
    async def list_accounts(self, *, offset: int = 0, limit: int = 100) -> tuple[list[PanelAccount], int | None]:
        """One page of the panel's accounts plus the panel's total (``None`` when unknown)."""
        ...


@runtime_checkable
class EventSource(Protocol):  # flag: event_source (PG-03: the panel pushes events; Melorin verifies them and registers itself)
    def verify_webhook(self, headers: Mapping[str, str], body: bytes, secret: str) -> bool: ...
    async def get_webhook_config(self, url: str | None = None) -> dict: ...
    async def connect_webhook(self, url: str, secret: str, **kw) -> dict: ...
    async def disconnect_webhook(self, url: str) -> dict: ...


@runtime_checkable
class TrafficReset(Protocol):  # flag: traffic_reset (the old optional ``reset_traffic`` method, now declared)
    async def reset_traffic(self, username: str) -> PanelAccount: ...


@runtime_checkable
class SubscriptionRotate(Protocol):  # flag: subscription_rotate
    async def rotate_subscription(self, username: str) -> PanelAccount: ...


# capability flag -> the protocol its methods must satisfy
CAPABILITY_PROTOCOLS: dict[str, type] = {
    "traffic_reset": TrafficReset,
    "subscription_rotate": SubscriptionRotate,
    "node_ops": NodeOps,
    "node_control": NodeOps,
    "usage_ops": UsageOps,
    "device_ops": DeviceOps,
    "bulk_ops": BulkOps,
    "admin_ops": AdminOps,
    "settings_ops": SettingsOps,
    "account_listing": AccountListing,
    "event_source": EventSource,
}


def supports(adapter, capability: str) -> bool:
    """True only when the adapter ADVERTISES ``capability`` and really implements the methods behind it. Use this instead of
    ``getattr(adapter, "...")`` guesses; a flag without methods (or methods without the flag) is a bug caught by contract tests."""
    if capability not in ALL_CAPABILITIES:
        return False
    try:
        advertised = adapter.capabilities().has(capability)
    except Exception:  # a misbehaving adapter must never take the caller down
        return False
    protocol = CAPABILITY_PROTOCOLS.get(capability)
    return advertised and (protocol is None or isinstance(adapter, protocol))


def require(adapter, capability: str) -> None:
    """Raise a PERMANENT PanelError (not a crash) when a caller asks an adapter for something it cannot do."""
    if not supports(adapter, capability):
        raise PanelError(ErrorKind.PERMANENT, f"{getattr(adapter, 'kind', 'panel')}: capability '{capability}' is not available")


class PanelAdapter(Protocol):
    kind: str

    async def health_check(self) -> bool: ...
    def capabilities(self) -> Capabilities: ...
    async def create_account(self, spec: AccountSpec) -> PanelAccount: ...
    async def get_account(self, username: str) -> PanelAccount | None: ...
    async def suspend_account(self, username: str) -> None: ...
    async def resume_account(self, username: str) -> None: ...
    async def extend_account(self, username: str, *, expire_at: dt.datetime | None, traffic_bytes: int) -> PanelAccount: ...
    async def revoke_account(self, username: str) -> None: ...
    # Optional (``Capabilities.traffic_reset``): zero the usage counter. Renewal falls back to a higher limit without it.
    # async def reset_traffic(self, username: str) -> PanelAccount: ...
    async def close(self) -> None: ...
    def normalize_status(self, raw: str) -> str: ...


def classify_http(status: int) -> ErrorKind:
    if status >= 500 or status in (408, 429):
        return ErrorKind.TRANSIENT
    return ErrorKind.PERMANENT
