import uuid

from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from melorin.core.db import Base, CreatedMixin, IdMixin, TimestampMixin


class Wallet(IdMixin, TimestampMixin, Base):
    """Per (user, store, kind, currency). balance is a projection of ledger entries, never the source of truth.

    A customer wallet belongs to the store where the customer buys. When a customer becomes a
    reseller, the SAME wallet they already hold in Main Store is used for reseller costs; the
    only addition is ResellerProfile.debt_limit, which lets reseller costs (not the owner's own
    purchases) take that wallet down to -debt_limit. Wallets of different stores never interact.
    """

    __tablename__ = "wallets"
    __table_args__ = (UniqueConstraint("user_id", "store_id", "kind", "currency"),)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="customer")  # customer (reseller_credit is legacy: merged into customer by migration 0026)
    currency: Mapped[str] = mapped_column(String(8), default="IRT")
    balance: Mapped[int] = mapped_column(BigInteger, default=0)


class LedgerTransaction(IdMixin, CreatedMixin, Base):
    __tablename__ = "ledger_transactions"
    kind: Mapped[str] = mapped_column(String(40), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    store_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    order_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    reverses_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ledger_transactions.id"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    currency: Mapped[str] = mapped_column(String(8))
    memo: Mapped[str | None] = mapped_column(String(500))


class LedgerEntry(IdMixin, CreatedMixin, Base):
    __tablename__ = "ledger_entries"
    transaction_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ledger_transactions.id"), index=True)
    account: Mapped[str] = mapped_column(String(120), index=True)
    wallet_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("wallets.id"), index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    balance_after: Mapped[int | None] = mapped_column(BigInteger)
