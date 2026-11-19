"""Regression tests for the second audit pass (V-07, V-09/V-10, V-12, V-24)."""

import hashlib
import hmac
import time
from urllib.parse import urlencode

import pytest

from melorin.core.errors import AppError
from melorin.domain import admin_access as aa
from melorin.modules.identity import service


def _init_data(bot_token: str, auth_date: int) -> str:
    pairs = {"auth_date": str(auth_date), "user": '{"id": 7}'}
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


def test_telegram_init_data_fresh_ok():
    assert service.verify_telegram_webapp(_init_data("tok", int(time.time())), "tok") == {"id": 7}


def test_telegram_init_data_expired_rejected():
    with pytest.raises(AppError) as e:
        service.verify_telegram_webapp(_init_data("tok", int(time.time()) - 90_000), "tok")
    assert e.value.code == "TELEGRAM_EXPIRED"


def test_telegram_init_data_future_rejected():  # V-12
    with pytest.raises(AppError) as e:
        service.verify_telegram_webapp(_init_data("tok", int(time.time()) + 3600), "tok")
    assert e.value.code == "TELEGRAM_EXPIRED"


def test_admin_routes_map_to_areas_and_owner_only_families_are_pinned():  # V-09/V-10
    """Walk the REAL route table (via the OpenAPI schema: FastAPI keeps included routers lazy, app.routes has no paths) and pin
    which families land in the owner-only ``system`` area, so a new route cannot silently become owner-only or manager-visible."""
    from melorin.app import app

    spec = app.openapi()
    checked = 0
    owner_only: set[str] = set()
    for path, ops in spec["paths"].items():
        if not path.startswith("/api/v1/admin/"):
            continue
        for method in ops:
            if method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue
            checked += 1
            area, _ = aa.area_for(path, method.upper())
            assert area in aa.AREAS or area in {"system", "self"}, (path, method, area)
            if area == "system":
                owner_only.add(path.split("/")[4])
    assert checked > 150, f"route walk found only {checked} admin operations: the test would be vacuous"
    assert owner_only == {"feature-flags", "integrations", "settings", "telegram"}
