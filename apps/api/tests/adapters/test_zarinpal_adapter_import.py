from importlib import import_module


def test_zarinpal_adapter_imports_with_payment_and_panel_contracts():
    module = import_module("melorin.modules.payments.adapters.zarinpal")

    assert module.ZarinpalAdapter.name == "zarinpal"
    assert module.ErrorKind.PERMANENT.value == "permanent"
    assert issubclass(module.PanelError, Exception)
