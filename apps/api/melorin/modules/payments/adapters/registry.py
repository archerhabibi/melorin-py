from melorin.core.errors import AppError
from melorin.modules.payments.adapters.manual_card import ManualCardAdapter
from melorin.modules.payments.adapters.zarinpal import ZarinpalAdapter
from melorin.modules.payments.adapters.destination import DestinationAdapter
from melorin.modules.payments.gateway_catalog import SUPPORTED_DESTINATIONS

_ADAPTERS = {
    a.name: a for a in (
        ManualCardAdapter(),
        ZarinpalAdapter(),
        DestinationAdapter("external_gateway", "gateway_link"),
        DestinationAdapter("crypto", "crypto_wallet"),
        DestinationAdapter("telegram_stars", "telegram_stars"),
    )
}


def get_adapter(name: str):
    a = _ADAPTERS.get(name)
    if not a:
        raise AppError("GATEWAY_UNKNOWN", "درگاه پرداخت نامعتبر است.", 400)
    return a


def register(adapter) -> None:
    """Extension point: plug in NextPay, crypto, Telegram Payments, ..."""
    _ADAPTERS[adapter.name] = adapter


def supported_destinations() -> dict:
    """Return PGClockBot-style card, gateway, crypto and Stars destination types."""
    return SUPPORTED_DESTINATIONS.copy()
