"""Panel URL policy and its short-lived verdict cache (audit T24)."""

from __future__ import annotations

import socket

import pytest

from melorin.modules.vpn.adapters import registry


@pytest.fixture(autouse=True)
def fresh_cache():
    registry._verdicts.clear()
    yield
    registry._verdicts.clear()


def resolver(monkeypatch, *ips):
    calls = []

    def fake(host, port, *a, **k):
        calls.append(host)
        return [(2, 1, 6, "", (ip, port)) for ip in ips]

    monkeypatch.setattr(registry.socket, "getaddrinfo", fake)
    return calls


def test_public_https_panel_is_accepted_and_looked_up_once_per_ttl(monkeypatch):
    calls = resolver(monkeypatch, "93.184.216.34")
    assert registry._public_panel_url("https://panel.example.com") is True
    assert registry._public_panel_url("https://panel.example.com") is True
    assert calls == ["panel.example.com"]


@pytest.mark.parametrize("ip", ["10.0.0.5", "127.0.0.1", "169.254.1.1", "192.168.1.10"])
def test_a_host_resolving_to_a_private_address_is_refused(monkeypatch, ip):
    resolver(monkeypatch, "93.184.216.34", ip)  # one private address among public ones is enough to refuse
    assert registry._public_panel_url("https://panel.example.com") is False


@pytest.mark.parametrize("url", ["http://panel.example.com", "https://user:pw@panel.example.com", "https:///x"])
def test_scheme_and_credentials_rules_do_not_need_dns(monkeypatch, url):
    calls = resolver(monkeypatch, "93.184.216.34")
    assert registry._public_panel_url(url) is False
    assert calls == []


def test_unresolvable_host_is_refused(monkeypatch):
    def boom(*a, **k):
        raise socket.gaierror("nope")

    monkeypatch.setattr(registry.socket, "getaddrinfo", boom)
    assert registry._public_panel_url("https://nope.example.com") is False


def test_verdict_expires_so_a_dns_change_is_noticed(monkeypatch):
    calls = resolver(monkeypatch, "93.184.216.34")
    clock = [1000.0]
    monkeypatch.setattr(registry.time, "monotonic", lambda: clock[0])
    assert registry._public_panel_url("https://panel.example.com") is True
    clock[0] += registry._VERDICT_TTL + 1
    resolver_calls_before = len(calls)
    assert registry._public_panel_url("https://panel.example.com") is True
    assert len(calls) == resolver_calls_before + 1


def test_a_refusal_is_retried_sooner_than_an_acceptance(monkeypatch):
    assert registry._REFUSAL_TTL < registry._VERDICT_TTL
