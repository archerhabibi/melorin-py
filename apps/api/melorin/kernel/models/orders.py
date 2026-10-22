import datetime as dt
import uuid

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from melorin.kernel.base import Base, CreatedMixin, IdMixin, TimestampMixin


class Order(IdMixin, TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("user_id", "store_id", "idempotency_key"),)
    number: Mapped[str] = mapped_column(String(6), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("products.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="purchase")  # purchase | renewal | test
    vpn_account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("vpn_accounts.id", use_alter=True))
    bundle_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("bundles.id"))
    selected_panel_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("panels.id"))
    requested_account_name: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), index=True)
    payment_method: Mapped[str] = mapped_column(String(20))  # wallet | manual_card | gateway | free
    channel: Mapped[str] = mapped_column(String(20), default="web")  # web | telegram | api | admin
    currency: Mapped[str] = mapped_column(String(8))
    unit_price: Mapped[int] = mapped_column(BigInteger)
    discount: Mapped[int] = mapped_column(BigInteger, default=0)
    total: Mapped[int] = mapped_column(BigInteger)
    reseller_cost: Mapped[int | None] = mapped_column(BigInteger)
    coupon_code: Mapped[str | None] = mapped_column(String(50))
    pricing_snapshot: Mapped[dict] = mapped_column(JSON)  # immutable after finalisation
    product_snapshot: Mapped[dict] = mapped_column(JSON)
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    provisioning_attempts: Mapped[int] = mapped_column(Integer, default=0)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    paid_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class OrderStateTransition(IdMixin, CreatedMixin, Base):
    __tablename__ = "order_state_transitions"
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("orders.id"), index=True)
    from_status: Mapped[str] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str | None] = mapped_column(String(500))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
