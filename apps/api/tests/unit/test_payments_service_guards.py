"""r14: payments service fails with a clear 404 AppError (not AttributeError) for an unknown payment or store."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from melorin.core.errors import AppError
from melorin.modules.payments import service


@pytest.mark.parametrize("fn", [service.mark_succeeded, service.mark_failed])
async def test_unknown_payment_is_a_404(fn):
    session = SimpleNamespace(get=AsyncMock(return_value=None))
    with pytest.raises(AppError) as exc:
        await fn(session, uuid.uuid4())
    assert exc.value.code == "PAYMENT_NOT_FOUND" and exc.value.status == 404


async def test_refund_of_a_payment_whose_store_vanished_is_a_404():
    payment = SimpleNamespace(status=service.P.SUCCEEDED, store_id=uuid.uuid4(), provider="zarinpal")
    session = SimpleNamespace(get=AsyncMock(side_effect=[payment, None]))
    with pytest.raises(AppError) as exc:
        await service.refund_payment(session, uuid.uuid4(), actor_id=None)
    assert exc.value.code == "STORE_NOT_FOUND" and exc.value.status == 404
