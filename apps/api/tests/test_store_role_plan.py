from melorin.modules.vpn import service_access, store_role


def test_store_role_is_smaller_than_the_service_role_and_has_no_key_or_admin_rights():
    body = store_role.role_body()
    perms = body["permissions"]
    assert set(perms) == {"users", "groups"} and perms["groups"] == {"read": True}
    assert all(perms["users"][a] for a in ("create", "read", "update", "delete"))
    assert set(store_role.STORE_PERMISSIONS) <= set(service_access.required_permissions()) | set(service_access.BASE_PERMISSIONS)
    plan = store_role.plan()
    assert plan["applied_by_melorin"] is False and "api_keys.*" in plan["withheld"]


async def test_plan_endpoint_is_admin_only_and_read_only():
    from _http import PASSWORD, add_user, api_client, totp_now
    from test_pasarguard_phase1_db import seed  # noqa: F401  (schema helpers live there)

    async with api_client() as (c, m, _main):
        import uuid

        url = f"/api/v1/admin/panels/{uuid.uuid4()}/store-role-plan"
        assert (await c.get(url)).status_code in (401, 403)
        await add_user(m, email="root@example.com", admin=True, totp=True)
        r = await c.post("/api/v1/auth/password/login", json={"email": "root@example.com", "password": PASSWORD, "totp_code": totp_now()})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        assert (await c.get(url, headers=h)).status_code == 404  # unknown panel


# ---- PG-12: explicit apply / revert (the panel is a fake) ------------------------------------------------------------
import json  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: E402

from _db import open_schema_engine  # noqa: E402
from melorin.core.errors import AppError  # noqa: E402
from melorin.kernel.models.vpn import Panel  # noqa: E402
from test_pasarguard_phase1_db import seed  # noqa: E402


class _FakeOwner:
    def __init__(self, fail=False):
        self.bodies, self.fail = [], fail

    async def ensure_role(self, body):
        if self.fail:
            from melorin.modules.vpn.adapters.base import ErrorKind, PanelError

            raise PanelError(ErrorKind.PERMANENT, "403 forbidden")
        self.bodies.append(body)
        return {"id": 9, **body}

    async def close(self):
        pass


@pytest.fixture
async def maker():
    async with open_schema_engine() as engine:
        yield async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_apply_creates_the_role_then_new_store_admins_use_it_and_revert_restores_operator(maker, monkeypatch):
    await seed(maker, [])
    owner = _FakeOwner()
    monkeypatch.setattr(store_role.registry, "build_adapter", lambda panel, credentials=None: owner)
    async with maker() as s:
        panel = (await s.scalars(select(Panel))).one()
        panel.kind = "pasarguard"
        assert store_role.plan(panel=panel)["applied"] is False
        with pytest.raises(AppError) as e:
            await store_role.apply(s, panel, bootstrap=None)
        assert e.value.code == "BOOTSTRAP_REQUIRED" and owner.bodies == []
        out = await store_role.apply(s, panel, bootstrap={"api_key": "OWNER"})
        assert out["applied"] and owner.bodies[0]["name"] == "melorin-store"
        assert panel.config["admin_role"] == "melorin-store" and "OWNER" not in json.dumps(panel.config)
        assert store_role.plan(panel=panel)["applied"] is True
        again = await store_role.apply(s, panel, bootstrap={"api_key": "OWNER"})  # idempotent
        assert again["previous"] == "melorin-store"
        back = await store_role.revert(s, panel)
        assert back == {"applied": False, "role": "operator"} and "admin_role" not in panel.config


@pytest.mark.asyncio
async def test_a_refused_role_changes_nothing(maker, monkeypatch):
    await seed(maker, [])
    monkeypatch.setattr(store_role.registry, "build_adapter", lambda panel, credentials=None: _FakeOwner(fail=True))
    async with maker() as s:
        panel = (await s.scalars(select(Panel))).one()
        panel.kind = "pasarguard"
        with pytest.raises(AppError) as e:
            await store_role.apply(s, panel, bootstrap={"api_key": "OWNER"})
        assert e.value.code == "STORE_ROLE_FAILED" and "admin_role" not in (panel.config or {})
