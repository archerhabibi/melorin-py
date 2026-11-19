import pytest

from melorin.core.invariants import InvariantViolation, require


def test_require_returns_value():
    assert require(5, "n") == 5
    assert require(0, "zero") == 0  # falsy but not None


def test_require_raises_on_none():
    with pytest.raises(InvariantViolation, match="refund operation"):
        require(None, "refund operation")
