from melorin.core.errors import AppError
from melorin.modules.payments.adapters.base import CallbackResult, IntentResult, RefundResult


class DestinationAdapter:
    """Manual-confirmation adapter for configurable gateway/crypto destinations."""

    requires_review = True

    def __init__(self, name: str, instruction_type: str):
        self.name = name
        self.instruction_type = instruction_type

    async def create_payment_intent(self, payment, *, callback_url: str, settings: dict) -> IntentResult:
        destination = settings.get(f"destination.{self.name}") or settings.get(f"gateway.{self.name}") or {}
        if not destination:
            raise AppError("PAYMENT_DESTINATION_MISSING", "مقصد پرداخت پیکربندی نشده است.", 409)
        return IntentResult(
            instructions={
                "type": self.instruction_type,
                "currency": payment.currency,
                "amount": payment.amount,
                "destination": destination,
                "note": "پس از پرداخت، رسید را برای بررسی ارسال کنید.",
            }
        )

    async def verify_callback(self, params, payment, *, settings) -> CallbackResult:
        return CallbackResult(str(payment.id), None, False, {"error": "manual_confirmation_required", **params})

    async def query_payment_status(self, payment, *, settings) -> str:
        return payment.status

    async def refund(self, payment, *, settings: dict) -> RefundResult:
        raise NotImplementedError(f"{self.name} refunds require audited manual compensation")

    def normalize_status(self, raw: str) -> str:
        return raw
