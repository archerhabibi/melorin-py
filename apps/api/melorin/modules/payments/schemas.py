import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt


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
    receipt_read: dict | None = None  # facts read off the receipt image (time, amount, card tail, reference)


def _receipt_read(p) -> dict | None:
    claim = (p.meta or {}).get("receipt_claim")
    if not claim:
        return None
    keys = ("paid_at", "amount_rial", "source_card_last4", "reference", "source", "ocr_engine")
    return {k: claim.get(k) for k in keys}


def payment_out(p) -> PaymentOut:
    return PaymentOut(
        id=p.id,
        store_id=p.store_id,
        user_id=p.user_id,
        purpose=p.purpose,
        order_id=p.order_id,
        provider=p.provider,
        amount=p.amount,
        currency=p.currency,
        status=p.status,
        has_receipt=p.receipt_file_id is not None,
        instructions=(p.meta or {}).get("instructions"),
        created_at=p.created_at,
        receipt_read=_receipt_read(p),
    )


class BankSmsSourceIn(BaseModel):
    """Everything is optional: only the sent fields change. The token is created with the source and shown once."""

    model_config = ConfigDict(extra="forbid")
    bank: str | None = None
    is_enabled: bool | None = None
    auto_verify: bool | None = None
    senders: list[str] | None = None
    settings: dict | None = None


class BankSmsLinkIn(BaseModel):
    payment_id: uuid.UUID


class BankSmsIgnoreIn(BaseModel):
    ignored: bool = True


class GraceSettingsIn(BaseModel):
    """Time-boxed manual review settings (all optional: only the sent fields change)."""

    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool | None = None
    minutes: StrictInt | None = None
    max_amount_rial: StrictInt | None = None
    max_exposure_rial: StrictInt | None = None
    max_open_per_user: StrictInt | None = None


class GraceResolveIn(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=300)
