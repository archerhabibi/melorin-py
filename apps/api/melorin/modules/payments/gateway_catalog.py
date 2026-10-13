"""Payment destination catalog inspired by PGClockBot's configurable methods.

These are destination types, not claims that credentials or provider sandboxes
are configured. Automatic settlement is only implemented by an adapter.
"""

SUPPORTED_DESTINATIONS = {
    "manual_card": {"currencies": {"IRT", "IRR"}, "requires_review": True},
    "zarinpal": {"currencies": {"IRT", "IRR"}, "requires_review": False},
    "external_gateway": {"currencies": {"IRT", "IRR", "USD", "EUR", "AED", "TRY"}, "requires_review": True},
    "crypto": {"currencies": {"USDT", "USD", "EUR"}, "requires_review": True},
    "telegram_stars": {"currencies": {"XTR"}, "requires_review": False},
}

SUPPORTED_CURRENCIES = ("IRT", "IRR", "USD", "EUR", "USDT", "AED", "TRY", "XTR")


def validate_destination(provider: str, currency: str) -> None:
    config = SUPPORTED_DESTINATIONS.get(provider)
    if not config or currency not in config["currencies"]:
        raise ValueError(f"unsupported payment destination: {provider}/{currency}")
