"""PG-05: least-privilege service admin + key lifecycle. The panel is a fake; the point is the order of steps and what is (not) stored."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import open_schema_engine
from melorin.core.crypto import decrypt, encrypt
from melorin.core.errors import AppError
from melorin.kernel.models.vpn import Panel
from melorin.modules.panelops import service_access
from melorin.modules.panel_integrations.adapters.base import ALL_CAPABILITIES, Capabilities
from melorin.modules.panel_integrations.adapters.pasarguard.capabilities import CAPABILITY_REQUIREMENTS, build_report, permission_granted
from test_pasarguard_service_db import seed

pytestmark = pytest.mark.asyncio


class FakeOwner:
    def __init__(self):
        self.calls, self.keys, self.next_id = [], {}, 100

    async def ensure_role(self, body):
        self.calls.append(("role", body["name"]))
        self.role = body
        return {"id": 7, **body}

    async def ensure_admin(self, username, password, *, role="operator", profile=None):
        self.calls.append(("admin", username, role))
        assert len(password) >= 32
        # PasarGuard's password rule (a random token_urlsafe sometimes broke it: 422 found on the live panel)
        assert sum(c.isdigit() for c in password) >= 2 and sum(c.isupper() for c in password) >= 2
        assert sum(c.islower() for c in password) >= 2 and any(not c.isalnum() for c in password)
        return {"id": 42, "username": username}

    async def create_api_key(self, admin_id, name, note=None):
        self.next_id += 1
        self.keys[self.next_id] = {"id": self.next_id, "admin_id": admin_id, "name": name, "api_key": f"secret-{self.next_id}"}
        self.calls.append(("key", admin_id))
        return dict(self.keys[self.next_id])

    async def delete_api_key(self, key_id):
        self.calls.append(("delete", key_id))
        self.keys.pop(int(key_id), None)

    async def list_api_keys(self, admin_id=None):
        return [{k: v for k, v in r.items() if k != "api_key"} for r in self.keys.values()]


def _report(role=service_access.ROLE_NAME, owner=False, drop=None):
    perms = service_access.role_permissions()
    if drop:
        section, _, action = drop.partition(".")
        perms[section].pop(action)
    declared = Capabilities(**dict.fromkeys(ALL_CAPABILITIES, True))
    return build_report(declared, role=role, is_owner=owner, permissions=perms)


class FakeCandidate:
    def __init__(self, report):
        self._report = report

    async def discover_capabilities(self):
        return self._report

    async def close(self):
        pass


@pytest.fixture
async def maker():
    async with open_schema_engine() as engine:
        yield async_sessionmaker(engine, expire_on_commit=False)


def wire(monkeypatch, owner, report):
    def fake(panel, credentials=None):
        return FakeCandidate(report) if credentials and credentials.get("api_key", "").startswith("secret-") else owner

    monkeypatch.setattr(service_access, "_adapter", fake)


async def test_role_holds_every_permission_melorin_needs_and_none_of_the_withheld():
    perms = service_access.role_permissions()
    for needed in [p for group in CAPABILITY_REQUIREMENTS.values() for p in group] + list(service_access.BASE_PERMISSIONS):
        assert permission_granted(perms, needed), needed
    for withheld in ("admins.delete", "nodes.create", "nodes.delete", "cores.create", "cores.delete", "groups.delete"):
        assert not permission_granted(perms, withheld), withheld
    assert "api_keys" not in perms and service_access.role_body()["name"] == "melorin-service"


async def test_plan_never_lists_a_permission_as_both_granted_and_withheld():
    plan = service_access.plan()
    both = set(plan["grants"]) & set(plan["withheld"])
    assert not both, both


async def test_provision_switches_melorin_to_the_verified_key_and_never_stores_the_old_one(maker, monkeypatch):
    await seed(maker, [])
    owner = FakeOwner()
    wire(monkeypatch, owner, _report())
    async with maker() as s:
        panel = (await s.scalars(select(Panel))).one()
        panel.kind = "pasarguard"
        panel.credentials_enc = encrypt(json.dumps({"api_key": "OWNER-KEY"}))
        out = await service_access.provision(s, panel, actor_id=None)
        assert out["switched"] is True and "secret" not in json.dumps(out)
        assert json.loads(decrypt(panel.credentials_enc)) == {"api_key": "secret-101"}
        assert panel.config["service_admin_id"] == 42 and panel.config["service_key_id"] == 101
        assert [c[0] for c in owner.calls] == ["role", "admin", "key"]  # owner key is not deleted
        with pytest.raises(AppError) as again:
            await service_access.provision(s, panel)
        assert again.value.code == "ALREADY_PROVISIONED"


async def test_a_key_that_is_not_the_service_role_is_rejected_and_removed_without_switching(maker, monkeypatch):
    await seed(maker, [])
    for bad in (_report(owner=True), _report(role="operator"), _report(drop="nodes.reconnect")):
        owner = FakeOwner()
        wire(monkeypatch, owner, bad)
        async with maker() as s:
            panel = (await s.scalars(select(Panel))).one()
            panel.kind = "pasarguard"
            panel.credentials_enc = encrypt(json.dumps({"api_key": "OWNER-KEY"}))
            with pytest.raises(AppError) as exc:
                await service_access.provision(s, panel)
            assert exc.value.code == "SERVICE_KEY_REJECTED"
            assert json.loads(decrypt(panel.credentials_enc)) == {"api_key": "OWNER-KEY"}  # still on the old credential
            assert not owner.keys  # the rejected key was deleted again


async def test_rotate_needs_bootstrap_replaces_key_and_deletes_the_old_one(maker, monkeypatch):
    await seed(maker, [])
    owner = FakeOwner()
    wire(monkeypatch, owner, _report())
    async with maker() as s:
        panel = (await s.scalars(select(Panel))).one()
        panel.kind = "pasarguard"
        panel.credentials_enc = encrypt(json.dumps({"api_key": "OWNER-KEY"}))
        await service_access.provision(s, panel)
        with pytest.raises(AppError) as exc:
            await service_access.rotate(s, panel, bootstrap={})
        assert exc.value.code == "BOOTSTRAP_REQUIRED"
        out = await service_access.rotate(s, panel, bootstrap={"api_key": "OWNER-KEY"})
        assert out["old_key_deleted"] is True and panel.config["service_key_id"] == 102
        assert json.loads(decrypt(panel.credentials_enc)) == {"api_key": "secret-102"} and list(owner.keys) == [102]
