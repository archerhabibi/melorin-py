"""Audit T24: the public-URL DNS check is cached so it does not block the loop on every adapter build."""

import socket

from melorin.modules.vpn.adapters import registry


def _fake(addr, calls):
    def fn(host, port, type=0):
        calls.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, port))]

    return fn


def test_dns_answer_is_cached(monkeypatch):
    registry._public_cache.clear()
    calls: list[str] = []
    monkeypatch.setattr(registry.socket, "getaddrinfo", _fake("93.184.216.34", calls))
    assert registry._public_panel_url("https://panel.example.com/") is True
    assert registry._public_panel_url("https://panel.example.com/x") is True
    assert calls == ["panel.example.com"]


def test_private_address_rejected_and_cached(monkeypatch):
    registry._public_cache.clear()
    calls: list[str] = []
    monkeypatch.setattr(registry.socket, "getaddrinfo", _fake("10.0.0.5", calls))
    assert registry._public_panel_url("https://inner.example.com") is False
    assert registry._public_panel_url("https://inner.example.com") is False
    assert len(calls) == 1


def test_lookup_failure_is_not_cached(monkeypatch):
    registry._public_cache.clear()

    def boom(*a, **k):
        raise socket.gaierror("down")

    monkeypatch.setattr(registry.socket, "getaddrinfo", boom)
    assert registry._public_panel_url("https://x.example.com") is False
    calls: list[str] = []
    monkeypatch.setattr(registry.socket, "getaddrinfo", _fake("93.184.216.34", calls))
    assert registry._public_panel_url("https://x.example.com") is True


def test_http_and_credentials_still_rejected():
    assert registry._public_panel_url("http://a.example.com") is False
    assert registry._public_panel_url("https://u:p@a.example.com") is False
