from pathlib import Path

from _source import read_source


def test_h008_runtime_guards_are_present():
    webhook = read_source(Path(__file__).parents[1].joinpath("melorin", "modules", "webhooks", "service.py"))
    registry = read_source(Path(__file__).parents[1].joinpath("melorin", "modules", "vpn", "adapters", "registry.py"))
    assert "WEBHOOK_DNS_CHANGED" in webhook
    assert "getaddrinfo" in webhook
    assert "PANEL_TLS_VERIFY_REQUIRED" in registry
