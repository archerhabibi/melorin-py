"""r13e: pay_with_wallet fails with a clear AppError (not AttributeError) when its store or the reseller owner is missing."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from melorin.core.errors import AppError
from melorin.modules.orders.service import payment


async def test_missing_store_is_a_404_app_error():
    session = SimpleNamespace(get=AsyncMock(return_value=None))
    order = SimpleNamespace(store_id=uuid.uuid4())
    with pytest.raises(AppError) as exc:
        await payment.pay_with_wallet(session, order)
    assert exc.value.code == "STORE_NOT_FOUND" and exc.value.status == 404


async def test_reseller_store_without_owner_never_reaches_the_wallet(monkeypatch):
    get_wallet = AsyncMock(return_value=SimpleNamespace(balance=0))
    monkeypatch.setattr(payment.wallet, "get_wallet", get_wallet)
    store = SimpleNamespace(id=uuid.uuid4(), kind="reseller", owner_user_id=None)
    profile = SimpleNamespace(sales_enabled=True, debt_limit=0)
    session = SimpleNamespace(scalar=AsyncMock(return_value=profile))
    order = SimpleNamespace(store_id=store.id, user_id=uuid.uuid4(), currency="IRT", reseller_cost=100, pricing_snapshot={})
    main = SimpleNamespace(id=uuid.uuid4())
    with pytest.raises(AppError) as exc:
        await payment.pay_with_wallet(session, order, store, main=main)
    assert exc.value.code == "STORE_OWNER_MISSING"
    assert get_wallet.await_count == 1  # only the customer wallet was looked up
