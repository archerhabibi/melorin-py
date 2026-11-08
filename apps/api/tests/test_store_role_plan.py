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
