from pathlib import Path

from _source import read_source


def test_h008_runtime_guards_are_present():
    webhook = read_source(Path(__file__).parents[2].joinpath("melorin", "modules", "webhooks", "service.py"))
    registry = read_source(Path(__file__).parents[2].joinpath("melorin", "modules", "panel_integrations", "adapters", "registry.py"))
    assert "_safe_resolved" in webhook and "sni_hostname" in webhook  # resolve once, connect to the validated address
    assert "getaddrinfo" in webhook
    assert "PANEL_TLS_VERIFY_REQUIRED" in registry
