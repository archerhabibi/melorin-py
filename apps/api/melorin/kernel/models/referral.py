import uuid

from sqlalchemy import BigInteger, Boolean, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from melorin.kernel.base import Base, CreatedMixin, IdMixin, TimestampMixin


class ReferralRelationship(IdMixin, CreatedMixin, Base):
    """Single-level, first-touch (v1.1): the first registered referrer wins and is immutable."""

    __tablename__ = "referral_relationships"
    __table_args__ = (UniqueConstraint("referred_user_id"),)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    referrer_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    referred_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))


class Commission(IdMixin, CreatedMixin, Base):
    __tablename__ = "commissions"
    __table_args__ = (
        UniqueConstraint("order_id", "kind"),
        UniqueConstraint("referred_user_id", "kind"),
    )
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("orders.id"))
    referrer_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    referred_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # signup_reward | commission
    amount: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), default="credited")  # credited | reversed
    ledger_tx_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reversed_amount: Mapped[int] = mapped_column(BigInteger, default=0)
    offset_amount: Mapped[int] = mapped_column(BigInteger, default=0)  # gross minus offset = paid out
    currency: Mapped[str | None] = mapped_column(String(8))


class CommissionRule(IdMixin, TimestampMixin, Base):
    """Admin-configured reward/commission plan. product_id NULL = default plan for the store."""

    __tablename__ = "commission_rules"
    __table_args__ = (UniqueConstraint("store_id", "product_id", "kind"),)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("products.id"))
    kind: Mapped[str] = mapped_column(String(20))  # signup_reward | commission
    model: Mapped[str] = mapped_column(String(10))  # fixed | percent
    value: Mapped[int] = mapped_column(BigInteger)  # amount or basis points
    max_amount: Mapped[int | None] = mapped_column(BigInteger)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class CommissionClawback(IdMixin, TimestampMixin, Base):
    """Outstanding reversal not covered by the referrer wallet; recovered from future commissions."""

    __tablename__ = "commission_clawbacks"
    __table_args__ = (UniqueConstraint("referrer_user_id", "store_id", "currency"),)
    referrer_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"))
    currency: Mapped[str] = mapped_column(String(8))
    outstanding: Mapped[int] = mapped_column(BigInteger, default=0)
