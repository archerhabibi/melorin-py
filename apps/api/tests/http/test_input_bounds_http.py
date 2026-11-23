"""A number the client sends that the database cannot store is a 422, never a 500 (audit finding BE-001)."""

from __future__ import annotations

import httpx
from fastapi import FastAPI
from sqlalchemy.exc import DataError

from _http import PASSWORD, add_user, api_client
from melorin.core import errors

AUTH = "/api/v1/auth"
BEYOND_BIGINT = 2**63


async def _login(c, maker, email="user@example.com"):
    await add_user(maker, email=email)
    r = await c.post(f"{AUTH}/password/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()["store_id"]


async def test_database_data_error_is_a_422_not_a_500():
    """The safety net: whatever bound is not declared, an out-of-range value must not become a 500 with a traceback."""
    app = FastAPI()
    errors.install(app)

    @app.get("/boom")
    async def boom():
        raise DataError("INSERT INTO payments ...", {}, Exception("value out of int64 range"))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/boom")
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "VALUE_OUT_OF_RANGE"
    assert "Traceback" not in r.text and "INSERT" not in r.text


async def test_offset_beyond_bigint_is_rejected_by_the_declared_bound():
    async with api_client() as (c, maker, _main):
        h, sid = await _login(c, maker)
        for params in ({"offset": BEYOND_BIGINT}, {"offset": -1}, {"limit": 0}, {"limit": 201}):
            r = await c.get(f"/api/v1/stores/{sid}/vpn-accounts", params=params, headers=h)
            assert r.status_code == 422, (params, r.status_code, r.text)
            assert r.json()["error"]["code"] == "VALIDATION_ERROR"
        assert (await c.get(f"/api/v1/stores/{sid}/vpn-accounts", params={"offset": 2**31 - 1}, headers=h)).status_code == 200


async def test_notifications_limit_is_declared_not_silently_clamped():
    async with api_client() as (c, maker, _main):
        h, sid = await _login(c, maker)
        assert (await c.get(f"/api/v1/stores/{sid}/notifications", params={"limit": 200}, headers=h)).status_code == 200
        assert (await c.get(f"/api/v1/stores/{sid}/notifications", params={"limit": 201}, headers=h)).status_code == 422
