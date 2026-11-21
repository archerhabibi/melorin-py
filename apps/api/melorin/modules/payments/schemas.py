import datetime as dt
import uuid

from melorin.domain import bank_sms as _dom
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


def _range(key: str, unit: str) -> str:
    """Human-readable allowed range of a bank-SMS setting, read from the domain rule table (never retyped here)."""
    lo, hi = _dom.SETTING_RANGES[key]
    return f"{lo} to {hi} {unit}"


class BankSmsSettingsIn(BaseModel):
    """Typed keys and value types of the bank-SMS matching settings.

    Ranges are documented here but enforced by the domain layer (``clean_settings``), so an out-of-range value keeps its
    stable ``BANK_SMS_SETTING_INVALID`` business error instead of a generic schema error. ``null`` resets a setting.
    """

    model_config = ConfigDict(extra="forbid")
    window_minutes: StrictInt | None = Field(
        default=None,
        description=f"How long a deposit SMS may lag behind or precede the payment request: {_range('window_minutes', 'minutes')}.",
    )
    time_tolerance_minutes: StrictInt | None = Field(
        default=None, description=f"Allowed gap between the receipt time and the SMS time: {_range('time_tolerance_minutes', 'minutes')}."
    )
    require_claimed_time: StrictBool | None = Field(default=None, description="The customer must state the time printed on the receipt.")
    max_auto_amount_rial: StrictInt | None = Field(
        default=None,
        description=f"Larger deposits are always reviewed by a human: {_range('max_auto_amount_rial', 'rial')}; null means no limit.",
    )
    account_number: str | None = Field(
        default=None, description=f"Store bank account number, digits only (Persian digits accepted): {_range('account_number', 'digits')}."
    )


class BankSmsSourceIn(BaseModel):
    """Everything is optional: only the sent fields change. The token is created with the source and shown once."""

    model_config = ConfigDict(extra="forbid")
    bank: str | None = None
    is_enabled: bool | None = None
    auto_verify: bool | None = None
    senders: list[str] | None = None
    settings: BankSmsSettingsIn | None = None


class BankSmsSettingsOut(BaseModel):
    """Effective settings: stored values with the domain defaults filled in."""

    window_minutes: int
    time_tolerance_minutes: int
    require_claimed_time: bool
    max_auto_amount_rial: int | None
    account_number: str | None


class BankSmsSourceOut(BaseModel):
    """The store's SMS source. The webhook token itself is never part of it (only ``has_token`` and the last 4 characters)."""

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
    status: str = Field(description="unmatched | matched | ambiguous | ignored | unparsed")
    direction: str | None = Field(description="deposit | withdrawal")
    amount_rial: int | None
    balance_rial: int | None
    occurred_at: dt.datetime | None
    serial: str | None
    sender: str | None
    payment_id: uuid.UUID | None
    matched_by: str | None = Field(description="auto | admin")
    note: str | None
    balance_gap: bool = Field(description="The balance does not follow the previous SMS (a message may be missing).")
    created_at: dt.datetime


class BankSmsOverviewOut(BaseModel):
    source: BankSmsSourceOut
    messages: list[BankSmsMessageOut]


class BankSmsSourceSavedOut(BaseModel):
    source: BankSmsSourceOut
    token: str | None = Field(description="Plaintext webhook token, present only on the response that creates the source; copy it once.")


class BankSmsTokenOut(BaseModel):
    token: str = Field(description="The new plaintext webhook token; the previous one stops working immediately. Shown once.")


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
    max_open_per_origin: StrictInt | None = None
    min_account_age_hours: StrictInt | None = None


class GraceResolveIn(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=300)


class ReceiptDupSettingsIn(BaseModel):
    """Per-store policy for a receipt picture that was already used: ``warn`` (default, accept and flag) or ``block``."""

    model_config = ConfigDict(extra="forbid")
    policy: str
