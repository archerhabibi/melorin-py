import datetime as dt
import uuid

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from melorin.kernel.base import Base, CreatedMixin, IdMixin, TimestampMixin


class LoyaltyProgram(IdMixin, TimestampMixin, Base):
    """The customer club of ONE store (docs/22). No row, or ``is_enabled`` false, means the store has no club."""

    __tablename__ = "loyalty_programs"
    __table_args__ = (UniqueConstraint("store_id"),)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    earn_unit: Mapped[int] = mapped_column(BigInteger, default=1000)  # currency units that make one earning step
    points_per_unit: Mapped[int] = mapped_column(Integer, default=1)
    max_points_per_order: Mapped[int | None] = mapped_column(Integer)
    first_order_bonus: Mapped[int] = mapped_column(Integer, default=0)
    referral_bonus: Mapped[int] = mapped_column(Integer, default=0)


class LoyaltyTier(IdMixin, TimestampMixin, Base):
    """A level of the store's ladder, reached by the points a customer has EARNED over his lifetime."""

    __tablename__ = "loyalty_tiers"
    __table_args__ = (UniqueConstraint("store_id", "min_points"),)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    min_points: Mapped[int] = mapped_column(Integer, default=0)
    multiplier_bp: Mapped[int] = mapped_column(Integer, default=10_000)  # 10000 = 1.0x on the points of later orders


class LoyaltyAccount(IdMixin, TimestampMixin, Base):
    """A customer's points purse in ONE store. ``balance`` is a locked projection of the ledger, never negative."""

    __tablename__ = "loyalty_accounts"
    __table_args__ = (UniqueConstraint("store_id", "user_id"), CheckConstraint("balance >= 0 AND debt >= 0", name="non_negative"))
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    balance: Mapped[int] = mapped_column(BigInteger, default=0)
    lifetime_earned: Mapped[int] = mapped_column(BigInteger, default=0)  # decides the tier; spending never lowers it
    debt: Mapped[int] = mapped_column(BigInteger, default=0)  # points owed back after a refund; recovered from future earnings


class LoyaltyTransaction(IdMixin, CreatedMixin, Base):
    """Append-only points ledger; ``idempotency_key`` makes every posting safe to retry."""

    __tablename__ = "loyalty_transactions"
    __table_args__ = (Index("ix_loyalty_transactions_store_user_created", "store_id", "user_id", "created_at"),)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("loyalty_accounts.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24))  # order_earn|first_order_bonus|referral_bonus|admin_grant|admin_deduct|redeem|reversal
    amount: Mapped[int] = mapped_column(BigInteger)  # signed: + earned, - spent or taken back
    balance_after: Mapped[int] = mapped_column(BigInteger)
    order_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("orders.id"), index=True)
    reward_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("loyalty_rewards.id"))
    reverses_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("loyalty_transactions.id"))
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    memo: Mapped[str | None] = mapped_column(String(255))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    debt_recovered: Mapped[int] = mapped_column(BigInteger, default=0)  # part of an earning that settled an older points debt


class LoyaltyReward(IdMixin, TimestampMixin, Base):
    """What a store lets its customers buy with points. v1 reward: wallet credit (``value`` currency units)."""

    __tablename__ = "loyalty_rewards"
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20), default="wallet_credit")
    value: Mapped[int] = mapped_column(BigInteger)
    cost_points: Mapped[int] = mapped_column(Integer)
    stock: Mapped[int | None] = mapped_column(Integer)  # None = unlimited
    per_user_limit: Mapped[int | None] = mapped_column(Integer)
    redeemed_count: Mapped[int] = mapped_column(Integer, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class LoyaltyRedemption(IdMixin, CreatedMixin, Base):
    """One reward taken by one customer: the points spent, the value paid out and the ledger rows that prove both."""

    __tablename__ = "loyalty_redemptions"
    __table_args__ = (UniqueConstraint("store_id", "user_id", "idempotency_key"),)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    reward_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("loyalty_rewards.id"), index=True)
    points_spent: Mapped[int] = mapped_column(Integer)
    value: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(8))
    ledger_tx_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # the wallet ledger transaction
    points_tx_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # the points ledger row
    idempotency_key: Mapped[str] = mapped_column(String(100))
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
