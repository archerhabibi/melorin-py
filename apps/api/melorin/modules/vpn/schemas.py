import datetime as dt
import uuid

from pydantic import BaseModel


class VpnAccountOut(BaseModel):
    id: uuid.UUID
    username: str
    status: str
    is_test: bool
    expires_at: dt.datetime | None
    traffic_limit_bytes: int
    traffic_used_bytes: int
    subscription_url: str | None
    links: list | None
    server_id: uuid.UUID | None
    created_at: dt.datetime
    updated_at: dt.datetime
    can_renew: bool = False  # inside the renewal window (up to 10 days after expiry) and not a test/revoked account
    renew_until: dt.datetime | None = None
    renew_note: str | None = None  # Core's own words for "why not renewable" (shown as is by every channel; None when renewable)
    store_id: uuid.UUID | None = None
    days_left: int | None = None  # None = no expiry
    usage_percent: int | None = None  # None = unlimited volume
    health: str = "active"  # active | expiring | expired | depleted | disabled
    can_return: bool = False  # مرجوعی: volume account, <= 3 days old, <= 5% used, not renewed, daily limit not reached
    return_note: str | None = None  # Core's own words for "why not returnable" (None when returnable)
    next_plan_queued: bool = False  # PG-09: a prepaid package is waiting; it starts by itself when the current one ends
    next_plan_queued_at: dt.datetime | None = None
    # mediator rule: ``live`` is False only when live reading is on and the panel could not answer; the numbers above are then empty
    # and ``live_note`` says "temporarily unavailable" (never an old number)
    live: bool = True
    live_note: str | None = None


class OwnerAccountOut(VpnAccountOut):
    """What a store owner sees for one of the store's customer accounts (the owner may renew them for the customer)."""

    customer_id: uuid.UUID
    customer_name: str | None = None
    is_own: bool = False  # True: the owner's own account; False: an account of one of the store's customers
    holder_label: str | None = None  # Core's words for whose account this is ("اکانت خودتان" / "مشتری: ...")


# ---------------------------------------------------------------- PG-10 account tools
class ToolOut(BaseModel):
    tool: str
    label: str
    write: bool
    available: bool
    reason: str | None = None  # Core's own words for "why not"


class UsagePointOut(BaseModel):
    at: str | None = None
    used_bytes: int


class UsageNodeOut(UsagePointOut):
    node_id: int | str


class UsageOut(BaseModel):
    period: str
    days: int
    points: list[UsagePointOut]
    by_node: list[UsageNodeOut] = []  # owner / admin only
    total_bytes: int


class PresenceOut(BaseModel):
    online_at: dt.datetime | None
    online_now: bool
    never_connected: bool
    remote_status: str | None = None
    lifetime_used_bytes: int | None = None
    last_synced_at: dt.datetime | None = None


class DeviceOut(BaseModel):
    hwid: str
    label: str
    platform: str | None = None
    first_seen: str | None = None
    last_seen: str | None = None


class DevicesOut(BaseModel):
    items: list[DeviceOut]
    count: int


class ReasonIn(BaseModel):
    reason: str | None = None


class AccountAdjustIn(BaseModel):
    add_days: int = 0
    add_traffic_gb: int = 0
    reason: str
