from melorin.modules.payments.adapters.base import CallbackResult, IntentResult, RefundResult


class ManualCardAdapter:
    """کارت‌به‌کارت: customer transfers, uploads a receipt, an admin approves."""

    name = "manual_card"
    requires_review = True

    async def create_payment_intent(self, payment, *, callback_url: str, settings: dict) -> IntentResult:
        card = settings.get("card.info") or {}
        return IntentResult(
            instructions={
                "type": "manual_card",
                "amount": payment.amount,
                "currency": payment.currency,
                "card_number": card.get("card_number"),
                "holder": card.get("holder"),
                "bank": card.get("bank"),
                "note": "پس از واریز، تصویر رسید را بارگذاری کنید.",
            }
        )

    async def verify_callback(self, params, payment, *, settings) -> CallbackResult:
        raise NotImplementedError("manual card has no callback")

    async def query_payment_status(self, payment, *, settings) -> str:
        return payment.status

    async def refund(self, payment, *, settings: dict) -> RefundResult:
        raise NotImplementedError("manual card refunds require an audited wallet compensation")

    def normalize_status(self, raw: str) -> str:
        return raw
