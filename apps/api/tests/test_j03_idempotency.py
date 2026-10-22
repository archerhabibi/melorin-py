from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_order_idempotency_insert_is_savepoint_protected():
    source = (ROOT / "melorin/modules/orders/service/create.py").read_text()  # index/slice on raw text
    section = source[
        source.index("    # The pre-check above") : source.index(
            "    session.add(OrderStateTransition", source.index("    # The pre-check above")
        )
    ]
    assert "async with session.begin_nested()" in section
    assert "await session.flush()" in section
    assert "except IntegrityError:" in section
    assert "return existing" in section


@pytest.mark.integration
@pytest.mark.asyncio
async def test_same_key_concurrency_contract():
    """Runtime companion: run scripts/e2e_smoke.py against PostgreSQL to exercise two sessions.

    This marker intentionally remains opt-in because it needs a migrated
    PostgreSQL database, Redis and seeded catalog data.
    """
    pytest.skip("requires the live PostgreSQL/Redis integration fixture")
