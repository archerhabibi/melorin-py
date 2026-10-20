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
    store_id: uuid.UUID | None = None
    days_left: int | None = None  # None = no expiry
    usage_percent: int | None = None  # None = unlimited volume
    health: str = "active"  # active | expiring | expired | depleted | disabled


class OwnerAccountOut(VpnAccountOut):
    """What a store owner sees for one of the store's customer accounts (the owner may renew them for the customer)."""

    customer_id: uuid.UUID
    customer_name: str | None = None
    is_own: bool = False  # True: the owner's own account; False: an account of one of the store's customers
