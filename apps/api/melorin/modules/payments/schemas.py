import datetime as dt
import uuid

from pydantic import BaseModel, Field


class TopupRequest(BaseModel):
    amount: int = Field(gt=0)
    provider: str = "manual_card"


class PaymentOut(BaseModel):
    id: uuid.UUID
    store_id: uuid.UUID
    user_id: uuid.UUID
    purpose: str
    order_id: uuid.UUID | None
    provider: str
    amount: int
    currency: str
    status: str
    has_receipt: bool
    instructions: dict | None
    created_at: dt.datetime


def payment_out(p) -> PaymentOut:
    return PaymentOut(
        id=p.id, store_id=p.store_id, user_id=p.user_id, purpose=p.purpose, order_id=p.order_id, provider=p.provider, amount=p.amount,
        currency=p.currency, status=p.status, has_receipt=p.receipt_file_id is not None, instructions=(p.meta or {}).get("instructions"), created_at=p.created_at,
    )
