"""Zarinpal v4 adapter (optional; online gateway for V1 not yet chosen)."""

import httpx

from melorin.core.errors import AppError
from melorin.modules.payments.adapters.base import CallbackResult, IntentResult, RefundResult
from melorin.modules.vpn.adapters.base import ErrorKind, PanelError

API = "https://payment.zarinpal.com/pg/v4/payment"
SANDBOX = "https://sandbox.zarinpal.com/pg/v4/payment"


class ZarinpalAdapter:
    name = "zarinpal"
    requires_review = False

    def _base(self, s: dict) -> str:
        return SANDBOX if (s.get("gateway.zarinpal") or {}).get("sandbox") else API

    def _merchant(self, s: dict) -> str:
        m = (s.get("gateway.zarinpal") or {}).get("merchant_id")
        if not m:
            raise AppError("GATEWAY_NOT_CONFIGURED", "درگاه پیکربندی نشده است.", 503)
        return m

    @staticmethod
    def _gateway_amount(payment) -> int:
        # Melorin stores IRT as the user-facing canonical unit. Zarinpal's
        # contract is rial-denominated, so convert only at this adapter edge.
        return payment.amount * 10 if payment.currency == "IRT" else payment.amount

    async def create_payment_intent(self, payment, *, callback_url: str, settings: dict) -> IntentResult:
        if payment.currency not in {"IRR", "IRT"}:
            raise PanelError(ErrorKind.PERMANENT, "Zarinpal adapter currently supports IRT/IRR only")
        body = {
            "merchant_id": self._merchant(settings),
            "amount": self._gateway_amount(payment),
            "currency": "IRR",
            "description": f"Melorin {payment.id}",
            "callback_url": callback_url,
            "metadata": {"order_id": str(payment.id), "melorin_currency": payment.currency},
        }
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{self._base(settings)}/request.json", json=body)
        d = r.json().get("data") or {}
        if d.get("code") != 100:
            raise AppError("GATEWAY_ERROR", "خطا در ایجاد پرداخت.", 502)
        auth = d["authority"]
        pay_host = "sandbox.zarinpal.com" if "sandbox" in self._base(settings) else "payment.zarinpal.com"
        return IntentResult(instructions={"type": "redirect", "redirect_url": f"https://{pay_host}/pg/StartPay/{auth}"}, external_ref=auth)

    async def verify_callback(self, params: dict, payment, *, settings: dict) -> CallbackResult:
        if payment.currency not in {"IRR", "IRT"}:
            return CallbackResult(str(payment.id), None, False, {"error": "unsupported_currency"})
        authority, status = params.get("Authority"), params.get("Status")
        # Fail closed: a callback without an Authority must never reach verify.json (None == None would pass the equality).
        if status != "OK" or not authority or authority != payment.external_ref:
            return CallbackResult(str(payment.id), authority, False, params)
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                f"{self._base(settings)}/verify.json",
                json={"merchant_id": self._merchant(settings), "amount": self._gateway_amount(payment), "authority": authority},
            )
        d = r.json().get("data") or {}
        ok = d.get("code") in (100, 101)  # 101 = already verified (duplicate callback)
        return CallbackResult(str(payment.id), authority, ok, {"verify": d, **params})

    async def query_payment_status(self, payment, *, settings) -> str:
        return payment.status

    async def refund(self, payment, *, settings: dict) -> RefundResult:
        if payment.currency not in {"IRR", "IRT"}:
            raise PanelError(ErrorKind.PERMANENT, "Zarinpal refund currently supports IRT/IRR only")
        token = (settings.get("gateway.zarinpal") or {}).get("access_token")
        if not token or not payment.external_ref:
            raise PanelError(ErrorKind.PERMANENT, "Zarinpal refund requires access_token and authority")
        body = {"merchant_id": self._merchant(settings), "authority": payment.external_ref}
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                f"{self._base(settings)}/refund.json",
                headers={"Authorization": f"Bearer {token}"},
                json=body,
            )
        data = r.json()
        payload = data.get("data") or {}
        code = payload.get("code")
        if code not in (100, 101):
            raise PanelError(
                ErrorKind.TRANSIENT if r.status_code >= 500 else ErrorKind.PERMANENT, f"Zarinpal refund failed: {payload or data}"
            )
        return RefundResult(
            external_ref=str(payload.get("ref_id") or payload.get("session") or payment.external_ref), status="succeeded", raw=data
        )

    def normalize_status(self, raw: str) -> str:
        return raw
