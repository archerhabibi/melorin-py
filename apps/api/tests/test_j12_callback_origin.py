from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_payment_callback_does_not_use_request_host():
    router = (ROOT / "melorin/modules/payments/router.py").read_text()
    config = (ROOT / "melorin/core/config.py").read_text()
    assert "request.base_url" not in router
    assert "public_api_url" in router
    assert "public_api_url" in config
    assert "https" in config
