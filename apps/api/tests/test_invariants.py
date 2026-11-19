import pytest

from melorin.core.invariants import InvariantViolation, require


def test_require_returns_value():
    assert require(5, "n") == 5
    assert require(0, "zero") == 0  # falsy but not None


def test_require_raises_on_none():
    with pytest.raises(InvariantViolation, match="refund operation"):
        require(None, "refund operation")


def test_bounded_callback_params_caps_keys_and_length():
    from melorin.modules.payments.service import bounded_callback_params

    out = bounded_callback_params({f"k{i}": "x" * 5000 for i in range(100)})
    assert len(out) == 20
    assert all(len(v) <= 200 for v in out.values())
