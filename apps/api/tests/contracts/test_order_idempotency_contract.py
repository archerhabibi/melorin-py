from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_order_idempotency_insert_is_savepoint_protected():
    source = (ROOT / "melorin/modules/orders/service/create.py").read_text()  # index/slice on raw text
    section = source[
        source.index("    # The pre-check above") : source.index(
            "    session.add(OrderStateTransition", source.index("    # The pre-check above")
        )
    ]
    assert "async with session.begin_nested()" in section
    assert "await session.flush()" in section
    assert "except IntegrityError" in section  # ``as exc`` since audit B904
    assert "return existing" in section
