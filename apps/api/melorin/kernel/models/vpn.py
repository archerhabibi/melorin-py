import datetime as dt
import uuid

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy import event
from sqlalchemy.orm import Mapped, mapped_column

from melorin.kernel.base import Base, CreatedMixin, IdMixin, TimestampMixin


class Panel(IdMixin, TimestampMixin, Base):
    __tablename__ = "panels"
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20))  # sanaei | pasarguard | mock
    base_url: Mapped[str] = mapped_column(String(300))
    credentials_enc: Mapped[str | None] = mapped_column(Text)  # encrypted JSON {username,password,...}
    config: Mapped[dict | None] = mapped_column(JSON)  # inbound ids, protocol options
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    health_status: Mapped[str] = mapped_column(String(20), default="unknown")
    last_health_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_health_error: Mapped[str | None] = mapped_column(Text)


class Server(IdMixin, TimestampMixin, Base):
    __tablename__ = "servers"
    name: Mapped[str] = mapped_column(String(100))
    panel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("panels.id"), index=True)
    location: Mapped[str | None] = mapped_column(String(100))
    capacity: Mapped[int] = mapped_column(Integer, default=500)
    product_codes: Mapped[list | None] = mapped_column(JSON)  # None = all products
    allow_test: Mapped[bool] = mapped_column(Boolean, default=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class VpnAccount(IdMixin, TimestampMixin, Base):
    __tablename__ = "vpn_accounts"
    username: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("orders.id"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("products.id"))
    server_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("servers.id"), index=True)
    panel_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("panels.id"))
    panel_ref: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), index=True)
    is_test: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    traffic_limit_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    traffic_used_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    subscription_url: Mapped[str | None] = mapped_column(Text)
    links: Mapped[list | None] = mapped_column(JSON)
    near_expiry_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class AccountReturn(IdMixin, CreatedMixin, Base):
    """A customer's return (مرجوعی) of one purchased account. One row per order (unique), also the daily-limit ledger."""

    __tablename__ = "account_returns"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("orders.id"), unique=True)
    vpn_account_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("vpn_accounts.id"), index=True)
    used_bytes: Mapped[int] = mapped_column(BigInteger, default=0)  # usage at the moment of the return
    limit_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    amount: Mapped[int] = mapped_column(BigInteger, default=0)  # refunded to the customer's wallet of this store


class ProvisioningAttempt(IdMixin, CreatedMixin, Base):
    __tablename__ = "provisioning_attempts"
    __table_args__ = (UniqueConstraint("order_id", "attempt_no"),)
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("orders.id"), index=True)
    vpn_account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("vpn_accounts.id"))
    attempt_no: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(20))  # create | extend
    status: Mapped[str] = mapped_column(String(20))  # running | succeeded | failed
    error_kind: Mapped[str | None] = mapped_column(String(20))  # transient | permanent | unknown
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class ReconciliationIssue(IdMixin, CreatedMixin, Base):
    __tablename__ = "reconciliation_issues"
    vpn_account_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("vpn_accounts.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    details: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | resolved | ignored


@event.listens_for(VpnAccount.user_id, "set")
def _forbid_owner_change(target, value, oldvalue, initiator):
    """V1.1: VPN Account ownership transfer is forbidden for customers AND Admin."""
    from sqlalchemy.orm.base import NO_VALUE, NEVER_SET

    if oldvalue in (NO_VALUE, NEVER_SET, None) or oldvalue == value:
        return value
    raise ValueError("VPN account ownership transfer is not allowed")
