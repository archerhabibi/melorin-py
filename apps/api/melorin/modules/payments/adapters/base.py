from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class IntentResult:
    instructions: dict = field(default_factory=dict)  # card info, redirect_url ...
    external_ref: str | None = None


@dataclass
class CallbackResult:
    payment_id: str | None
    external_ref: str | None
    succeeded: bool
    raw: dict


@dataclass
class RefundResult:
    external_ref: str | None
    status: str
    raw: dict


class PaymentAdapter(Protocol):
    name: str
    requires_review: bool

    async def create_payment_intent(self, payment, *, callback_url: str, settings: dict) -> IntentResult: ...
    async def verify_callback(self, params: dict, payment, *, settings: dict) -> CallbackResult: ...
    async def query_payment_status(self, payment, *, settings: dict) -> str: ...
    async def refund(self, payment, *, settings: dict) -> RefundResult: ...
    def normalize_status(self, raw: str) -> str: ...
