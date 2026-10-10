from pathlib import Path


def test_h008_runtime_guards_are_present():
    webhook = Path(__file__).parents[1].joinpath("melorin", "modules", "webhooks", "service.py").read_text()
    registry = Path(__file__).parents[1].joinpath("melorin", "modules", "vpn", "adapters", "registry.py").read_text()
    assert "WEBHOOK_DNS_CHANGED" in webhook
    assert "getaddrinfo" in webhook
    assert "PANEL_TLS_VERIFY_REQUIRED" in registry
