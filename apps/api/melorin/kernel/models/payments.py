import datetime as dt
import uuid

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from melorin.kernel.base import Base, CreatedMixin, IdMixin, TimestampMixin


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


class BankSmsSource(IdMixin, TimestampMixin, Base):
    """Where a store's bank deposit SMS come from (card-to-card auto verification). One row per store.

    The webhook token is shown once and only its SHA-256 is kept, so a database leak cannot be used to feed fake SMS.
    """

    __tablename__ = "bank_sms_sources"
    __table_args__ = (UniqueConstraint("store_id"),)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    bank: Mapped[str] = mapped_column(String(30), default="mehr_iran")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_verify: Mapped[bool] = mapped_column(Boolean, default=False)  # credit the wallet without a human click
    token_hash: Mapped[str | None] = mapped_column(String(64))
    token_hint: Mapped[str | None] = mapped_column(String(8))
    senders: Mapped[list | None] = mapped_column(JSON)  # optional allow-list of SMS sender numbers / names
    settings: Mapped[dict | None] = mapped_column(JSON)  # window_minutes, time_tolerance_minutes, ...
    last_received_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class BankSmsMessage(IdMixin, CreatedMixin, Base):
    """One received bank SMS. ``fingerprint`` makes forwarder retries idempotent; ``payment_id`` is unique, so one
    deposit can pay for at most one payment and one payment is covered by at most one deposit."""

    __tablename__ = "bank_sms_messages"
    __table_args__ = (UniqueConstraint("store_id", "fingerprint"), UniqueConstraint("payment_id"))
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("bank_sms_sources.id"))
    fingerprint: Mapped[str] = mapped_column(String(64))
    serial: Mapped[str | None] = mapped_column(String(64))
    direction: Mapped[str | None] = mapped_column(String(12))  # deposit | withdrawal
    amount_rial: Mapped[int | None] = mapped_column(BigInteger)
    balance_rial: Mapped[int | None] = mapped_column(BigInteger)
    occurred_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    sender: Mapped[str | None] = mapped_column(String(64))
    raw_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), index=True)  # unmatched | matched | ambiguous | ignored | unparsed
    payment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("payments.id"))
    matched_by: Mapped[str | None] = mapped_column(String(10))  # auto | admin
    note: Mapped[str | None] = mapped_column(String(300))
    balance_gap: Mapped[bool] = mapped_column(Boolean, default=False)  # balance does not follow the previous SMS
