from types import SimpleNamespace

import pytest

from melorin.modules.payments.adapters.zarinpal import ZarinpalAdapter
from melorin.modules.payments.gateway_catalog import validate_destination


def test_zarinpal_converts_irt_only_at_gateway_boundary():
    adapter = ZarinpalAdapter()
    assert adapter._gateway_amount(SimpleNamespace(amount=1250, currency="IRT")) == 12500
    assert adapter._gateway_amount(SimpleNamespace(amount=1250, currency="IRR")) == 1250


@pytest.mark.parametrize(
    ("provider", "currency"),
    [("manual_card", "IRT"), ("external_gateway", "USD"), ("crypto", "USDT"), ("telegram_stars", "XTR")],
)
def test_supported_payment_destination_currency(provider, currency):
    validate_destination(provider, currency)


def test_destination_currency_mismatch_is_rejected():
    with pytest.raises(ValueError):
        validate_destination("crypto", "IRT")
