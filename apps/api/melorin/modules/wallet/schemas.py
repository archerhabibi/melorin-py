import datetime as dt
import uuid

from pydantic import BaseModel, Field


class WalletOut(BaseModel):
    id: uuid.UUID
    store_id: uuid.UUID
    kind: str
    currency: str
    balance: int
    # The owner's numeric Telegram ID (identities.subject of provider "telegram"); None when no Telegram is linked.
    telegram_id: str | None = None


class LedgerEntryOut(BaseModel):
    transaction_id: uuid.UUID
    kind: str
    amount: int
    balance_after: int | None
    memo: str | None
    order_id: uuid.UUID | None
    created_at: dt.datetime


class AdjustWallet(BaseModel):
    amount: int = Field(description="positive=credit, negative=debit (smallest unit)")
    reason: str | None = Field(default=None, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=100)
