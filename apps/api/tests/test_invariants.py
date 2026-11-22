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


def test_set_vpn_status_postcondition_is_a_real_check_not_an_assert():
    from melorin.core.invariants import InvariantViolation
    from melorin.domain.order_state import VpnSource, VpnStatus, set_vpn_status

    class Stuck:  # a broken model whose status write is silently dropped
        status = "active"

        def __setattr__(self, name, value):
            if name != "status":
                object.__setattr__(self, name, value)

    with pytest.raises(InvariantViolation, match="after transition"):
        set_vpn_status(Stuck(), VpnStatus.SUSPENDED, source=VpnSource.ACCOUNT_TOOLS)
