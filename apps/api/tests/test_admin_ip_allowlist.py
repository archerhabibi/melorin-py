"""Behavioural checks for the admin-panel IP allowlist (OFF by default)."""

from types import SimpleNamespace

import pytest

from melorin.core import deps, integrations
from melorin.core.context import client_ip
from melorin.core.errors import AppError


def _admin():
    return SimpleNamespace(is_super_admin=True, totp_enabled=True, allowed_ips=None)


async def _call(monkeypatch, access, ip):
    async def fake(_session):
        return {**integrations.ADMIN_ACCESS_DEFAULT, **access}

    monkeypatch.setattr(integrations, "get_admin_access", fake)
    token = client_ip.set(ip)
    try:
        return await deps.require_admin(None, _admin())
    finally:
        client_ip.reset(token)


def test_default_is_off():
    assert integrations.ADMIN_ACCESS_DEFAULT == {"enabled": False, "ips": []}


@pytest.mark.parametrize("ip", ["8.8.8.8", "?", "testclient", None])
async def test_off_by_default_does_not_restrict(monkeypatch, ip):
    assert await _call(monkeypatch, {}, ip)
    assert await _call(monkeypatch, {"enabled": False, "ips": ["203.0.113.10/32"]}, ip)


async def test_enabled_allows_listed_ip_and_cidr(monkeypatch):
    assert await _call(monkeypatch, {"enabled": True, "ips": ["203.0.113.10/32"]}, "203.0.113.10")
    assert await _call(monkeypatch, {"enabled": True, "ips": ["198.51.100.0/24"]}, "198.51.100.77")


@pytest.mark.parametrize("ip", ["8.8.8.8", "203.0.113.11", "?", "unix", "testclient", "", None])
async def test_enabled_blocks_others_with_403_not_500(monkeypatch, ip):
    with pytest.raises(AppError) as exc:
        await _call(monkeypatch, {"enabled": True, "ips": ["203.0.113.10/32"]}, ip)
    assert exc.value.code == "ADMIN_IP_NOT_ALLOWED"


async def _put(monkeypatch, enabled, ips, my_ip):
    from melorin.core import audit
    from melorin.modules.admin import integrations as router

    saved = {}

    async def fake_save(_s, key, cfg):
        saved[key] = cfg

    class S:
        async def commit(self):
            pass

    monkeypatch.setattr(router.integrations, "save", fake_save)
    monkeypatch.setattr(audit, "record", lambda *a, **k: None)
    token = client_ip.set(my_ip)
    try:
        out = await router.update_admin_access(router.AdminAccessIn(enabled=enabled, ips=ips), SimpleNamespace(id=1), S())
    finally:
        client_ip.reset(token)
    return out, saved


async def test_panel_refuses_self_lockout_empty_and_invalid(monkeypatch):
    for enabled, ips, code in [
        (True, ["203.0.113.10"], "ADMIN_IP_LOCKOUT"),
        (True, [], "ADMIN_IP_EMPTY"),
        (True, ["nope"], "ADMIN_IP_INVALID"),
    ]:
        with pytest.raises(AppError) as exc:
            await _put(monkeypatch, enabled, ips, "198.51.100.5")
        assert exc.value.code == code


async def test_panel_saves_when_own_ip_listed_and_can_disable(monkeypatch):
    out, saved = await _put(monkeypatch, True, ["198.51.100.0/24", "198.51.100.0/24"], "198.51.100.5")
    assert out["enabled"] and out["ips"] == ["198.51.100.0/24"]
    out, _ = await _put(monkeypatch, False, [], "198.51.100.5")
    assert out["enabled"] is False
