import uuid

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, String, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from melorin.kernel.base import Base, CreatedMixin, IdMixin, TimestampMixin


class ReferralRelationship(IdMixin, CreatedMixin, Base):
    """Single-level, first-touch, PER STORE: inside one store the first referrer wins and is immutable.

    A person who joins a second store (a reseller's shop or bot) has an independent relationship there; the referral
    programs of different stores never see each other (docs/17).
    """

    __tablename__ = "referral_relationships"
    __table_args__ = (UniqueConstraint("store_id", "referred_user_id"),)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    referrer_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    referred_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))


class Commission(IdMixin, CreatedMixin, Base):
    __tablename__ = "commissions"
    __table_args__ = (
        UniqueConstraint("order_id", "kind"),
        # one signup reward per referred customer PER STORE (a customer may legitimately earn one in each store he joined)
        UniqueConstraint("store_id", "referred_user_id", "kind"),
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
    """Reward/commission plan of ONE store (set by Admin, or by the reseller for his own store). product_id NULL = the store's default plan."""

    __tablename__ = "commission_rules"
    __table_args__ = (
        UniqueConstraint("store_id", "product_id", "kind"),
        # NULLs never collide in the constraint above, so the default plan (product_id IS NULL) gets its own guard
        Index(
            "uq_commission_rules_store_kind_default",
            "store_id",
            "kind",
            unique=True,
            postgresql_where=text("product_id IS NULL"),
            sqlite_where=text("product_id IS NULL"),
        ),
    )
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
