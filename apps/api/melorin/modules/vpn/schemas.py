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
