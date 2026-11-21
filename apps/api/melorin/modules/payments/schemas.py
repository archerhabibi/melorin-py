import datetime as dt
import uuid
from typing import Literal

from melorin.modules.payments.redaction import strip_secrets
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
    meta = p.meta or {}
    claim = meta.get("receipt_claim")
    ocr_state = (meta.get("receipt_ocr") or {}).get("state")  # "pending" while the worker has not read the picture yet
    if not claim and not ocr_state:
        return None
    keys = ("paid_at", "amount_rial", "source_card_last4", "reference", "source", "ocr_engine")
    return {**{k: (claim or {}).get(k) for k in keys}, "ocr_state": ocr_state}


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
        instructions=strip_secrets((p.meta or {}).get("instructions")),  # also heals rows stored before the V-15 fix
        created_at=p.created_at,
        receipt_read=_receipt_read(p),
    )


class BankSmsSettingsIn(BaseModel):
    """The tuning knobs. Types are declared here for the OpenAPI contract; ranges and unknown keys are still decided by
    ``bank_sms.clean_settings`` (stable ``BANK_SMS_SETTING_INVALID`` errors), so extras are accepted and rejected there.
    ``null`` resets a knob to its default."""

    model_config = ConfigDict(extra="allow")
    window_minutes: StrictInt | None = None
    time_tolerance_minutes: StrictInt | None = None
    require_claimed_time: StrictBool | None = None
    max_auto_amount_rial: StrictInt | None = None
    account_number: str | None = None


class BankSmsSourceIn(BaseModel):
    """Everything is optional: only the sent fields change. The token is created with the source and shown once."""

    model_config = ConfigDict(extra="forbid")
    bank: str | None = None
    is_enabled: bool | None = None
    auto_verify: bool | None = None
    senders: list[str] | None = None
    settings: BankSmsSettingsIn | None = None


class BankSmsLinkIn(BaseModel):
    payment_id: uuid.UUID


class BankSmsIgnoreIn(BaseModel):
    ignored: bool = True


# ----- Bank SMS: response models (the admin and reseller screens read the same shapes; they feed the generated TS types) -----
BankSmsStatus = Literal["unmatched", "matched", "ambiguous", "ignored", "unparsed"]


class BankSmsSettingsOut(BaseModel):
    window_minutes: int
    time_tolerance_minutes: int
    require_claimed_time: bool
    max_auto_amount_rial: int | None
    account_number: str | None


class BankSmsSourceOut(BaseModel):
    store_id: uuid.UUID
    configured: bool
    bank: str
    is_enabled: bool
    auto_verify: bool
    has_token: bool
    token_hint: str | None
    senders: list[str]
    settings: BankSmsSettingsOut
    last_received_at: dt.datetime | None


class BankSmsMessageOut(BaseModel):
    id: uuid.UUID
    store_id: uuid.UUID
    status: BankSmsStatus
    direction: Literal["deposit", "withdrawal"] | None
    amount_rial: int | None
    balance_rial: int | None
    occurred_at: dt.datetime | None
    serial: str | None
    sender: str | None
    payment_id: uuid.UUID | None
    matched_by: Literal["auto", "admin"] | None
    note: str | None
    balance_gap: bool
    created_at: dt.datetime


class BankSmsOverviewOut(BaseModel):
    source: BankSmsSourceOut
    messages: list[BankSmsMessageOut]


class BankSmsSaveOut(BaseModel):
    """``token`` is present only when the save created the source (shown once, never stored in clear)."""

    source: BankSmsSourceOut
    token: str | None


class BankSmsTokenOut(BaseModel):
    token: str


class BankSmsReconcileOut(BaseModel):
    checked: int
    matched: int


class GraceSettingsIn(BaseModel):
    """Time-boxed manual review settings (all optional: only the sent fields change)."""

    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool | None = None
    minutes: StrictInt | None = None
    max_amount_rial: StrictInt | None = None
    max_exposure_rial: StrictInt | None = None
    max_open_per_user: StrictInt | None = None
    max_open_per_origin: StrictInt | None = None
    min_account_age_hours: StrictInt | None = None


class GraceResolveIn(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=300)


class ReceiptDupSettingsIn(BaseModel):
    """Per-store policy for a receipt picture that was already used: ``warn`` (default, accept and flag) or ``block``."""

    model_config = ConfigDict(extra="forbid")
    policy: str
