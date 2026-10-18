from pathlib import Path

from _source import read_source

ROOT = Path(__file__).resolve().parents[1]


def test_main_payment_settings_have_first_class_forms():
    extra = (ROOT.parent / "admin-web/src/AdminExtra.jsx").read_text()
    payments = (ROOT.parent / "admin-web/src/PaymentsView.jsx").read_text()
    # Payment gateway settings now live inside the redesigned Payments screen.
    assert '"پرداخت‌ها": PaymentsView' in extra
    assert "GatewaySettings" in payments
    assert "card.info" in payments and "gateway.zarinpal" in payments
    assert "تنظیمات پیشرفته سیستم" in extra


def test_zarinpal_is_validated_as_a_supported_destination():
    source = read_source(ROOT / "melorin/modules/payments/gateway_catalog.py")
    service = read_source(ROOT / "melorin/modules/payments/service.py")
    assert '"zarinpal"' in source
    assert 'provider in {"zarinpal", "external_gateway", "crypto", "telegram_stars"}' in service


def test_telegram_topup_surfaces_core_configuration_errors():
    source = read_source(ROOT.parent / "telegram-main/runner.py")
    assert "except CoreError as exc:" in source
    assert "⚠️ {exc.message}" in source


def test_wallet_callback_parses_nested_amount_payload():
    source = read_source(ROOT.parent / "telegram-main/runner.py")
    assert 'prefix, _, raw = value.partition(":")' in source
    assert 'if raw == "custom":' in source
    assert "re.fullmatch" in source


def test_panel_health_job_accepts_sync_or_async_adapter_close():
    source = read_source(ROOT / "melorin/worker/jobs.py")
    assert "inspect.isawaitable(result)" in source
