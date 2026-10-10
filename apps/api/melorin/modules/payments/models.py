import datetime as dt
import uuid

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from melorin.core.db import Base, CreatedMixin, IdMixin, TimestampMixin


class Payment(IdMixin, TimestampMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("provider", "external_ref"),
        UniqueConstraint("user_id", "store_id", "idempotency_key"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(20))  # wallet_topup | order
    order_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("orders.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30))  # manual_card | zarinpal | ...
    amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(20), index=True)
    external_ref: Mapped[str | None] = mapped_column(String(200))
    receipt_file_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("file_objects.id"))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    meta: Mapped[dict | None] = mapped_column(JSON)


class PaymentAttempt(IdMixin, CreatedMixin, Base):
    """Raw gateway interactions (callbacks, verifies) for traceability."""

    __tablename__ = "payment_attempts"
    payment_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("payments.id"), index=True)
    action: Mapped[str] = mapped_column(String(30))
    result: Mapped[str] = mapped_column(String(30))
    data: Mapped[dict | None] = mapped_column(JSON)
