from pathlib import Path

from _source import read_source

ROOT = Path(__file__).resolve().parents[1]


def test_payment_callback_does_not_use_request_host():
    router = read_source(ROOT / "melorin/modules/payments/router.py")
    config = read_source(ROOT / "melorin/core/config.py")
    assert "request.base_url" not in router
    assert "public_api_url" in router
    assert "public_api_url" in config
    assert "https" in config
