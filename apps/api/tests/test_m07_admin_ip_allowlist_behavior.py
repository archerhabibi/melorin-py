"""Behavioural checks for MELORIN_ADMIN_ALLOWED_IPS enforcement in require_admin."""
from types import SimpleNamespace

import pytest

from melorin.core import deps
from melorin.core.context import client_ip
from melorin.core.errors import AppError


def _admin():
    return SimpleNamespace(is_super_admin=True, totp_enabled=True, allowed_ips=None)


async def _call(monkeypatch, allowed, ip):
    monkeypatch.setattr(deps, "get_settings", lambda: SimpleNamespace(admin_allowed_ips=allowed))
    token = client_ip.set(ip)
    try:
        return await deps.require_admin(_admin())
    finally:
        client_ip.reset(token)


async def test_allowlisted_ip_and_cidr_are_accepted(monkeypatch):
    assert await _call(monkeypatch, ["203.0.113.10/32"], "203.0.113.10")
    assert await _call(monkeypatch, ["198.51.100.0/24"], "198.51.100.77")


@pytest.mark.parametrize("ip", ["8.8.8.8", "203.0.113.11", "?", "unix", "testclient", "", None])
async def test_other_or_unresolvable_ips_get_403_not_500(monkeypatch, ip):
    with pytest.raises(AppError) as exc:
        await _call(monkeypatch, ["203.0.113.10/32"], ip)
    assert exc.value.code == "ADMIN_IP_NOT_ALLOWED"


@pytest.mark.parametrize("ip", ["8.8.8.8", "?", "testclient", None])
async def test_empty_allowlist_does_not_restrict_or_crash(monkeypatch, ip):
    assert await _call(monkeypatch, [], ip)
