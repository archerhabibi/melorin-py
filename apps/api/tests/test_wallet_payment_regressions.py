from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_main_payment_settings_have_first_class_forms():
    source = (ROOT.parent / "admin-web/src/AdminExtra.jsx").read_text()
    assert "PaymentSettings" in source
    assert "card.info" in source and "gateway.zarinpal" in source
    assert "تنظیمات پیشرفته سیستم" in source


def test_zarinpal_is_validated_as_a_supported_destination():
    source = (ROOT / "melorin/modules/payments/gateway_catalog.py").read_text()
    service = (ROOT / "melorin/modules/payments/service.py").read_text()
    assert '"zarinpal"' in source
    assert 'provider in {"zarinpal", "external_gateway", "crypto", "telegram_stars"}' in service


def test_telegram_topup_surfaces_core_configuration_errors():
    source = (ROOT.parent / "telegram-main/runner.py").read_text()
    assert 'except CoreError as exc:' in source
    assert '⚠️ {exc.message}' in source
