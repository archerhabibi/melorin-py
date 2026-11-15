"""r14: an identity or link code that points at a missing user fails with a 404 AppError, not an AttributeError."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from melorin.core.errors import AppError
from melorin.modules.identity import service


@pytest.mark.parametrize("user_id", [uuid.uuid4(), None])
async def test_missing_user_is_a_404(user_id):
    session = SimpleNamespace(get=AsyncMock(return_value=None))
    with pytest.raises(AppError) as exc:
        await service._owner_of(session, user_id)
    assert exc.value.code == "USER_NOT_FOUND" and exc.value.status == 404
